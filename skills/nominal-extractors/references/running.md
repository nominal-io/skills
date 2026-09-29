# Running extractors and debugging jobs

## Triggering an ingest

Fetch the target and live active image first. Compare its inputs, parameters, output format
and timestamp defaults with the intended capture. Reuse settled per-capture sources,
parameters, tag vocabulary and start-time evidence from code, README and the conversation.
Resolve missing essentials before uploading: required files, validated parameter values,
target dataset/scope, and a trustworthy capture start where relative time needs one. Do not
invent a start, tag or deployment target to make the call runnable.

Uploaders can pick the extractor in the Nominal web app with no code at all; that self-serve
path is the main reason to prefer an extractor over local conversion. Scripted ingests use the
Python SDK:

```python
extractor = client.get_containerized_extractor(extractor_rid)
if extractor.active_image is None:
    raise RuntimeError("Extractor has no active image")
dataset = client.get_dataset("ri.catalog.gov-staging.dataset.abc123")

job = dataset.add_containerized(
    extractor,                                # ContainerizedExtractor or its rid
    sources={"RAW_FILE": "captures/flight_042.bin"},
    arguments={"THRESHOLD": "0.8"},
    tags={"vehicle": "N042", "campaign": "sept-flight-test"},
)
```

- **`sources`** — each input's *environment variable*, as registered on the active image,
  mapped to a local file path. The SDK uploads the files, then triggers the ingest. Keys must
  match the active image's inputs (`extractor.active_image.inputs` is the live list), a
  missing `required` input raises before anything uploads, and the extractor must have an
  active image.
- **`arguments`** — parameter values, keyed by environment variable, as strings.
- **`tags`** — applied to all data from this run and readable in-container through
  `_NOMINAL_ADDITIONAL_TAGS`. Use tags to partition recurring uploads within one dataset
  instead of creating a dataset per file.
- **`timestamp_column` / `timestamp_type`** (together) — override the image's default for
  this ingest, for every output that does not declare its own `timestampMetadata`. See the authoritative
  [timestamp metadata precedence](contract.md#timestamp-metadata-precedence); capture-specific
  starts belong with this capture, not an image default.

`asset.add_containerized(data_scope_name, extractor, sources, ...)` (also on a `Run`) is the
same call against a data scope, merging the scope's required tags into `tags` (yours win on collisions).
That scope/upload merge says nothing about collisions with row/record tags; use distinct keys
or verify the required behavior as described in [modeling](modeling.md#tags-start-from-intended-comparisons).

The `nom` CLI does not trigger containerized ingests; use the SDK or the web app.

## Waiting for the result

Containerized ingest is asynchronous and can emit many files, so the call returns an
`IngestionJob` immediately. Waiting has two stages: the container finishes producing files,
then those files finish ingesting. A manifest extractor's outputs do not exist as dataset
files until its container exits. `job.as_files_ingested()` (`nominal>=1.167`) waits out both
stages, re-reading the job's file list while it runs:

```python
import datetime

from nominal.core.dataset_file import IngestStatus
from nominal.core.exceptions import NominalIngestFailed, NominalIngestTimeout

try:
    files = list(job.as_files_ingested(timeout=datetime.timedelta(hours=1)))
except NominalIngestFailed:
    raise RuntimeError(f"extraction failed — see {job.nominal_url}")
except NominalIngestTimeout:
    raise TimeoutError(f"still running after an hour — see {job.nominal_url}")

unsuccessful = [file for file in files if file.ingest_status is not IngestStatus.SUCCESS]
if unsuccessful:
    raise RuntimeError(f"{len(unsuccessful)} files did not ingest successfully — see {job.nominal_url}")
```

- A job that ends `FAILED` raises `NominalIngestFailed`; the timeout raises
  `NominalIngestTimeout` naming the stage it was blocked on.
- Yielded files may have failed individually; check each `ingest_status`.
- A `CANCELLED` job yields whatever ingested and logs a warning rather than raising.
- An empty list passes these checks, so also compare observed outputs with the representative
  contract: expected counts where established, tables, channels and destination-specific
  outputs. Do not equate manifest declarations with dataset-file count: video and other
  destinations need their own verification, and a one-to-one mapping is not guaranteed.

On older SDKs, `as_files_ingested()` reads the file list once, so a call made before the
container exits can return `[]` immediately. There, poll `job.refresh().status` while it is
`SUBMITTED`, `QUEUED` or `IN_PROGRESS` under a deadline, require `COMPLETED`, then wait on
`job.dataset_files()` with `nominal.core.wait_for_files_to_ingest`. Loop while the status is
known-running rather than until it reaches a fixed terminal set: an unrecognized status maps to
`UNKNOWN`, which is never terminal.

The rest of the handle:

```python
job.refresh()       # re-reads from the server; status is a snapshot without it
job.status          # SUBMITTED → QUEUED → IN_PROGRESS → COMPLETED | FAILED | CANCELLED
job.dataset_files() # the DatasetFiles produced as of this call
job.produced_file_count
job.cancel()        # stop a job that is still running
job.nominal_url     # the job's page in the Nominal app
```

## Verify the resulting data

A successful container exit plus successful file ingestion establishes execution, not the
meaning of the data. For the representative capture, inspect selected expected values,
channel names and units/conversions, absolute start/end bounds, alignment with known events
or comparison channels, and actual tag keys/values and partitions. Check the agreed empty,
filtered and malformed-record behavior, including that each rejected case fails with its
agreed error code. Verify video/log or other destinations separately when they are part of
the contract. Missing expected outputs are a failure to validate even when every observed
dataset file succeeded.

Report the image version/RID observed for the run, target dataset/scope, job RID/link, file
statuses and semantic checks actually performed. The active image fetched before submission
is only a snapshot; if activation could have raced with submission, verify the job's image
from live job details rather than asserting that snapshot ran. Name limits such as unavailable
data queries or unverified video output. Put routine results in the existing workflow output,
not a new report or progress registry. On resume, fetch live extractor/job/file state and
continue from that evidence rather than treating saved handles as current.

## Debugging a failed job

Work from the outside in.

**1. Open `job.nominal_url`.** The job page shows status, produced files, the recorded
failure and the container's captured stdout/stderr; the Python `IngestionJob` does not expose
the failure detail. The log capture lands in a log dataset in the workspace and keeps **only
the first 1 MiB of each attempt**, so a verbose extractor loses its own traceback off the end;
a log that stops mid-run is usually the cap, not a hang. A failed run may show a second
attempt.

**2. Classify the failure.** The platform resolves a failed container to a code and message
from the extractor's termination-log document, else the image's exit-code mapping for that
status, else a platform fallback (see the
[contract](contract.md#exit-status-and-structured-errors)). The recorded failure and the
log's last lines, where the Python runtime prints the structured JSON before the traceback,
show which applied:

- An extractor-defined code (`MALFORMED_INPUT`, `NO_DATA`, ...) — the code classified the
  failure; its message and the log say why.
- `UNKNOWN` with "Extractor failed with exit code N" — the container exited non-zero without a
  valid termination-log document and N has no mapping. Either an unexpected failure (read the
  stack trace) or a reporting gap to close with `@error` or an exit-code mapping.
  A run killed at the time limit (about 50 minutes) also lands here, or on the mapping for
  the kill's exit status; look for pathological input or quadratic work.
- `EXTRACTOR_OOM_KILLED` — memory exhausted; stream instead of loading whole files.
- `OUTPUT_UPLOAD_FAILED` — collecting outputs failed after the container exited: usually a
  missing or unparseable `manifest.json`, a listed file that is missing or outside
  `$OUTPUT_DIR`, or, in single-file mode, anything other than exactly one entry in
  `$OUTPUT_DIR`. Compare the outputs with the [contract](contract.md#manifestjson).
- `IMAGE_PULL_FAILED`, `EXTRACTOR_UNSCHEDULABLE` — the image or scheduling stage. Recheck the
  image archive, and escalate platform faults with the job link.

**3. Read the Python runtime's advisory warnings** near the top of the log, when it is the
entrypoint:

- *"required parameter ... has no value set"* — the request omitted an argument the image
  registered as required.
- *"input ... is not present at ..."* — a registered input wasn't mounted, usually an optional
  one the request didn't supply.
- *"output directory contains file(s) not passed to ..."* (at the end) — the code wrote files
  it never declared, and they were not ingested.
- *"Context input/parameter lookups are legacy"* — see
  [migrating](authoring.md#migrating-context-lookups).

**4. Match the signature:**

- *"`@manifest_extractor` disagrees with the image's registered output format"* — code and
  registration disagree; re-register or switch decorators. A direct implementation should
  make the same check against `_NOMINAL_OUTPUT_FORMAT`.
- *exec format error*, or the container exits instantly with no stack trace — wrong
  architecture of the image or of the binary inside it. Confirm with
  `docker image inspect <tag> --format 'arch={{.Architecture}}'` and rebuild for amd64.
- *`ModuleNotFoundError`* or a missing shared library — a dependency is missing from the
  image; nothing carries over from your dev machine. It can also mean the dependency *is* in
  the image but was installed under `$HOME`, which the runtime mounts empty over: see
  [registration](registration.md#write-the-dockerfile).
- *permission denied* reading a shipped file or writing outside `$OUTPUT_DIR`/`$HOME` — the
  image assumed its own `USER` or root; the platform runs a different non-root UID.
- *ingestion fails before the container ran, complaining about timestamp metadata* — the image
  was registered without a default (an older registration path) and the request supplied no
  override.
- *a manifest error after the outputs were collected* — the manifest has no outputs, or pairs
  a file with the wrong `ingestType` for its extension. Compare it with the
  [contract](contract.md#manifestjson).
- *channel names lack their prefix, units are missing, or videos never appear* — the
  deployment's ingest route ignores those manifest options; see
  [deployment differences](contract.md#deployment-differences).

**5. `COMPLETED` but no data visible.** `COMPLETED` proves the container exited 0 and its
declared outputs were accepted. With the Python runtime, a run that declared nothing cannot
land here: finalization raises and the job shows `FAILED`. That leaves:

- the code declared some file, but not the one carrying the data — the stray-file warning
  names it;
- the declared file is empty because a broad `except` swallowed a parse failure;
- the timestamp column or unit is wrong, so the data landed at a time nobody is looking at;
- tags or a channel prefix are filtering it out of view;
- the file is still ingesting — job status and each file's `ingest_status` are separate, so
  check `job.dataset_files()` before concluding data is missing.

A direct implementation has none of the runtime's declaration guarantees; check its
`manifest.json` first.

**6. Reproduce locally.** The same code runs under `extractor.run(env={...}, exit=False)`, a
native test harness, or the [conformance check](contract.md#check-conformance-locally) with
the failing input mounted, which is almost always faster than iterating through platform
ingests.

## Recurring workflows

Once the image is active, reuse the agreed contract for recurring uploads.

- **Scripted batch** — collect the jobs from the whole loop *before* waiting on any of them;
  they run server-side in parallel, so waiting inside the loop serializes work that needn't
  be. Then wait on each job and check its files as above.
- **Operator self-serve** — users upload through the web app and pick the extractor, no SDK
  involved. The input suffixes decide which extractors the app offers for a file.
- **Version upgrades** — register the new tag and activate it; in-flight jobs finish on the
  image they started with.
