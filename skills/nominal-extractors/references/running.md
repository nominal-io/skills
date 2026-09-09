# Running extractors and debugging jobs

## Triggering an ingest

```python
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
  this ingest, applied uniformly to every output file. Per-output manifest metadata still
  wins over it.

`DataScope.add_containerized(data_scope_name, extractor, sources, ...)` is the same call
against a scope, merging the scope's required tags into `tags` (yours win on collisions).

There is no CLI path for triggering a containerized ingest — the SDK or the web app. This is
the one lifecycle step `nom container` does not cover.

## Tracking the job

Containerized ingest is asynchronous and can emit many files, so the call returns an
`IngestionJob` immediately, and waiting has **two stages**: the container has to finish
producing files, and only then do those files exist to be waited on as they ingest.

```python
import time

from nominal.core import IngestionJobStatus, wait_for_files_to_ingest

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
done, still_ingesting = wait_for_files_to_ingest(job.dataset_files())  # timeout=, return_when=
```

Two details that look like style but aren't:

**Stage 1 can't be skipped.** `job.dataset_files()` returns the files that exist *when it is
called*, and `job.as_files_ingested()` calls it exactly once. Run either right after
`add_containerized` and it sees an empty list, so `list(job.as_files_ingested())` returns `[]`
immediately, having waited for nothing — indistinguishable from a successful wait over zero
outputs. Once the job is `COMPLETED` the file list is complete and `as_files_ingested()` is
fine for stage 2.

**The loop tests the running set, not a terminal set.** `IngestionJobStatus` maps any status
a newer server adds into `UNKNOWN`. Waiting *while* the status is known-running exits on
anything unrecognized and the `COMPLETED` check makes that loud; waiting *until* the status
is in a fixed terminal set spins forever instead, since `UNKNOWN` is never terminal. The
deadline covers a server that adds a new non-terminal status.

The rest of the handle:

```python
job.refresh()       # re-reads from the server; status is a snapshot without it
job.status          # SUBMITTED → QUEUED → IN_PROGRESS → COMPLETED | FAILED | CANCELLED
job.dataset_files() # the DatasetFiles produced as of this call
job.produced_file_count
job.cancel()        # stop a job that is still running
job.nominal_url     # the job's page in the Nominal app
```

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
  architecture. Rebuild with `--platform linux/amd64`.
- *`ModuleNotFoundError`* — a dependency is missing from the image. Nothing carries over from
  your dev machine.
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

Once the image is registered, triggering is the only per-file step.

- **Scripted batch** — collect the jobs from the whole loop *before* waiting on any of them;
  they run server-side in parallel, so waiting inside the loop serializes work that needn't
  be. Then apply the two-stage wait per job. A batch is where skipping stage 1 hurts most: an
  empty snapshot per job makes the whole batch look instantly finished.
- **Operator self-serve** — users upload through the web app and pick the extractor, no SDK
  involved. This is the main reason to prefer an extractor over local conversion.
- **Version upgrades** — register the new tag and `set_active_image`; in-flight jobs finish on
  the image they started with.
