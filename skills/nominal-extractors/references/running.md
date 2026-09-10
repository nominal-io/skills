# Running extractors and debugging jobs

## Triggering an ingest

Fetch the target and live active image first. Compare its inputs, parameters, output format
and timestamp defaults with the intended capture. Reuse settled per-capture sources,
parameters, tag vocabulary and start-time evidence from code, README and the conversation.
Resolve missing essentials before uploading: required files, validated parameter values,
target dataset/scope, and a trustworthy capture start where relative time needs one. Do not
invent a start, tag or deployment target to make the call runnable.

```python
extractor = client.get_containerized_extractor(extractor_rid)
active_image = extractor.active_image
if active_image is None:
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
- **`tags`** — applied to all data from this run and readable in-container as
  `ctx.additional_tags`. Use tags to partition recurring uploads within one dataset instead of
  creating a dataset per file.
- **`timestamp_column` / `timestamp_type`** (together) — override the image's default for
  this ingest. See the authoritative
  [timestamp metadata contract](authoring.md#timestamp-metadata-contract) for precedence and
  supported types; capture-specific starts belong with this capture, not an image default.

`DataScope.add_containerized(data_scope_name, extractor, sources, ...)` is the same call
against a scope, merging the scope's required tags into `tags` (yours win on collisions).
That scope/upload merge says nothing about collisions with row/record tags; use distinct keys
or verify the required behavior as described in [modeling](modeling.md#tags-start-from-intended-comparisons).

There is no CLI path for triggering a containerized ingest — the SDK or the web app. This is
the one lifecycle step `nom container` does not cover.

## Tracking the job

Containerized ingest is asynchronous and can emit many files, so the call returns an
`IngestionJob` immediately, and waiting has **two stages**: the container has to finish
producing files, and only then do those files exist to be waited on as they ingest.

```python
import datetime
import time

from nominal.core import IngestionJobStatus, wait_for_files_to_ingest
from nominal.core.dataset_file import IngestStatus

RUNNING = (IngestionJobStatus.SUBMITTED, IngestionJobStatus.QUEUED, IngestionJobStatus.IN_PROGRESS)

# 1. the container run
deadline = time.monotonic() + 3600
while job.refresh().status in RUNNING:
    if time.monotonic() > deadline:
        raise TimeoutError(f"extraction still {job.status.name} — see {job.nominal_url}")
    time.sleep(2)
if job.status is not IngestionJobStatus.COMPLETED:
    raise RuntimeError(f"extraction {job.status.name} — see {job.nominal_url}")

# 2. the files it produced
files = job.dataset_files()
done, still_ingesting = wait_for_files_to_ingest(
    files, timeout=datetime.timedelta(minutes=30)
)
if still_ingesting:
    raise TimeoutError(f"{len(still_ingesting)} files still ingesting — see {job.nominal_url}")
unsuccessful = [file for file in done if file.ingest_status is not IngestStatus.SUCCESS]
if unsuccessful:
    raise RuntimeError(f"{len(unsuccessful)} files did not ingest successfully — see {job.nominal_url}")
```

The wait's `done` list includes failed, deleted and unknown statuses; it does not mean
success. Require both no remaining files and SUCCESS for every returned file. Choose bounded
timeouts suitable for the capture. Empty lists pass these checks, so also compare observed
outputs with the representative contract: expected counts where established, tables,
channels and destination-specific outputs. Do not universally equate manifest declarations with dataset-file count: video and
other destinations need their own verification, and one-to-one mapping is not guaranteed.

Two timing details matter:

**Stage 1 can't be skipped.** `job.dataset_files()` returns the files that exist *when it is
called*, and `job.as_files_ingested()` calls it exactly once. Run either before extraction finishes and it can see an empty or partial list. An empty
snapshot makes `list(job.as_files_ingested())` return `[]` immediately, having waited for
nothing; a partial snapshot misses later outputs. After `COMPLETED`, enumerate the produced dataset files and perform stage 2, including
explicit status checks. This only verifies that dataset-file view, not every output destination.

**The loop tests the running set, not a terminal set.** `IngestionJobStatus` maps any status
a newer server adds into `UNKNOWN`. Waiting *while* the status is known-running exits on
anything unrecognized and the `COMPLETED` check makes that loud; waiting *until* the status
is in a fixed terminal set spins forever instead, since `UNKNOWN` is never terminal. The
deadline bounds a job that remains in a known-running status.

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
filtered and malformed-record behavior. Verify video/log or other destinations separately
when they are part of the contract. Missing expected outputs are a failure to validate even
when every observed dataset file succeeded.

Report the image version/RID observed for the run, target dataset/scope, job RID/link, file
statuses and semantic checks actually performed. The active image fetched before submission
is only a snapshot; if activation could have raced with submission, verify the job's image
from live job details rather than asserting that snapshot ran. Name limits such as unavailable
data queries or unverified video output. Put routine results in the existing workflow output,
not a new report or progress registry. On resume, fetch live extractor/job/file state and
continue from that evidence rather than treating saved handles as current.

## Debugging a failed job

Work from the outside in.

**1. Open `job.nominal_url`.** The job page shows status, produced files, and the container's
captured stdout/stderr: the runtime's startup line (mode, function name, input count), its
contract warnings, and the final traceback. The capture lands in a log dataset in the
workspace and is **capped at 1 MiB per job**, so a verbose extractor can lose its own
traceback off the end — if the log looks truncated mid-run, that's the cap, not a hang.

**2. Read the runtime's advisory warnings** near the top of the log:

- *"required parameter ... has no value set"* — the request omitted an argument the image
  registered as required.
- *"input ... is not present at ..."* — a registered input wasn't mounted, usually an optional
  one the request didn't supply.
- *"output directory contains file(s) not passed to ..."* (at the end) — the code wrote files
  it never declared, and they were not ingested.

**3. Match the signature:**

- *"`@manifest_extractor` disagrees with the image's registered output format"* — code and
  registration disagree; re-register or switch decorators.
- *exec format error*, or the container exits instantly with no Python traceback — wrong
  architecture. Confirm with
  `docker image inspect <tag> --format 'arch={{.Architecture}}'` and rebuild with
  `--platform linux/amd64`.
- *`ModuleNotFoundError`* — a dependency is missing from the image; nothing carries over from
  your dev machine. It can also mean the dependency *is* in the image but was installed under
  `$HOME`, which the runtime mounts empty over: see
  [registration](registration.md#build-and-verify-amd64).
- *ingestion fails before the container ran, complaining about timestamp metadata* — the image
  was registered without a default (an older registration path) and the request supplied no
  override.

**4. `COMPLETED` but no data visible.** Start from what `COMPLETED` proves: the container
exited 0, so the runtime finalized at least one declared output. A run that declared nothing
cannot land here — `_finalize` raises and the job shows `FAILED`. That leaves:

- the code declared some file, but not the one carrying the data — the stray-file warning
  names it;
- the declared file is empty because a broad `except` swallowed a parse failure;
- the timestamp column or unit is wrong, so the data landed at a time nobody is looking at;
- tags or a channel prefix are filtering it out of view;
- the file is still ingesting — job status and each file's `ingest_status` are separate, so
  check `job.dataset_files()` before concluding data is missing.

If the entrypoint is hand-rolled rather than using this runtime, none of the declaration
guarantees hold. Check that first.

**5. Reproduce locally.** The same code path runs under `extractor.run(env={...}, exit=False)`
or under `docker run` with the input mounted (see `authoring.md`), which is almost always
faster than iterating through platform ingests.

## Recurring workflows

Once the image is active, reuse the agreed contract for recurring uploads.

- **Scripted batch** — collect the jobs from the whole loop *before* waiting on any of them;
  they run server-side in parallel, so waiting inside the loop serializes work that needn't
  be. Then apply the two-stage wait per job. A batch is where skipping stage 1 hurts most: an
  empty snapshot per job makes the whole batch look instantly finished.
- **Operator self-serve** — users upload through the web app and pick the extractor, no SDK
  involved. This is the main reason to prefer an extractor over local conversion.
- **Version upgrades** — register the new tag and `set_active_image`; in-flight jobs finish on
  the image they started with.
