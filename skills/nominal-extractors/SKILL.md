---
name: nominal-extractors
description: Build, test, register, and run Nominal containerized extractors — custom Docker images the Nominal platform runs during ingest to parse proprietary or unsupported file formats into datasets. Use this whenever the user mentions containerized extractors, custom extractors, nominal.experimental.extractor, @single_file_extractor / @manifest_extractor, register_image, add_containerized, extractor manifests, or asks how to ingest a file format Nominal doesn't natively support (binary telemetry, vendor logger output, packed/proprietary formats), how to convert files server-side during ingest, or how to debug a containerized ingest job.
---

# Nominal Containerized Extractors

A containerized extractor is a Docker image that Nominal runs server-side during ingest.
The platform mounts the uploaded raw files into the container, runs your code, and ingests
whatever your code writes to the output directory. Once registered, anyone in the workspace
can upload files in that format, from the SDK or the web app, without the parsing code on
their machine.

## Where extractors fit in Nominal's data model

Nominal stores time-series data in **datasets**, built from ingested **files**. Each ingest
parses a file's columns or records into **channels**, places samples in time using timestamp
metadata, and optionally applies **tags** that partition the data within the dataset (per
test-run, per vehicle).

`Dataset` has native ingest methods for the formats the platform parses itself:
`add_tabular_data` (CSV/Parquet), `add_avro_stream`, `add_journal_json` (logs), `add_mcap`,
`add_video`, `add_mcap_video`, `add_ardupilot_dataflash`.

A containerized extractor runs your code in that same pipeline. Use one when:

- the format is proprietary or unsupported (binary telemetry, packed structs, vendor logger
  output, CSV dialects needing preprocessing);
- the format recurs, so the parsing logic should live in one versioned place instead of on
  each engineer's laptop;
- non-developers upload the files through the web app, so the conversion has to happen
  without them running anything.

For a one-off conversion with a script you already have, convert locally and call
`dataset.add_tabular_data(...)` instead.

Two SDK surfaces are involved. Do not mix them up:

| Surface | Runs where | Import |
|---|---|---|
| Authoring runtime (the extractor's own code) | Inside the container, during ingest | `nominal.experimental.extractor` |
| Management & triggering (create/register/activate/run) | On your machine | `nominal.core` via `NominalClient` |

A **ContainerizedExtractor** carries identity (name, description). The **ContainerImage**s
registered against it carry the execution contract (inputs, parameters, output format,
default timestamp metadata). Exactly one image is active at a time, so you can register a
new version and switch over atomically.

## Lifecycle

1. **Decide the shape** — which values are inputs vs parameters, how timestamps are
   encoded, what the tags are — `references/modeling.md`
2. **Author** the extractor function — `references/authoring.md`
3. **Test locally** with `my_extractor.run(env={...}, exit=False)` — no Docker or platform
   access needed — `references/authoring.md` (Local testing section)
4. **Build** the image for `linux/amd64` and `docker save` it to a tarball —
   `references/registration.md`
5. **Register and activate** the image against an extractor — `references/registration.md`
6. **Trigger ingests** with `Dataset.add_containerized` and track the `IngestionJob` —
   `references/running.md`

Read the reference file for the stage you're working on before writing code. Each stage has
contract details — exact env variables, timestamp resolution rules, format restrictions —
that are easy to get subtly wrong from memory.

Step 1 is the one people skip and the one that is expensive to undo: inputs and parameters
are fixed at registration, and the timestamp and tag choices shape every query written
against the data afterward. If the shape isn't settled, read `modeling.md` first.

## The output contract: write manifest extractors

**New extractors use `@manifest_extractor`, registered with `output_format=MANIFEST`.** It
is the current contract and a strict superset of the alternative: it describes each output
file individually, so one image can emit several files, mix telemetry with logs and video,
and set per-file timestamps, tag columns, and channel prefixes.

`@single_file_extractor` is the original contract, still supported for images registered
with `PARQUET`, `CSV`, or `AVRO_STREAM`. Use it to maintain one of those, not for new work —
not even when the extractor produces a single table today. Declaring one file through the
manifest contract costs nothing, and the choice is expensive to reverse: the output format
is fixed at registration, so changing it later requires registering a new image.

| | `@manifest_extractor` (use this) | `@single_file_extractor` (existing images) |
|---|---|---|
| Registered `output_format` | `MANIFEST` | `PARQUET`, `CSV`, or `AVRO_STREAM` |
| Outputs | Any number, mixed formats | Exactly one file |
| Declare with | `ctx.add_tabular` / `add_avro_stream` / `add_journal_json` / `add_video` | `ctx.set_output(path)` |
| Per-output tag columns, channel prefixes, timestamps | Yes | No |
| Video outputs | Yes (recent platform versions) | No |

Whichever you use, the decorator and the registered format must agree. `Extractor.run` fails
at startup if they disagree, rather than emitting output the pipeline rejects.

## Minimal end-to-end example

Extractor code (`extract.py`, runs inside the container):

```python
import pandas as pd

from nominal.experimental.extractor import ManifestExtractorContext, manifest_extractor


@manifest_extractor
def convert(ctx: ManifestExtractorContext) -> None:
    df = parse_proprietary(ctx.input("RAW_FILE"))       # your parsing logic
    threshold = float(ctx.get_param("THRESHOLD", "0.5"))  # params are always strings

    out = ctx.output_dir / "telemetry.parquet"
    df[df.quality > threshold].to_parquet(out)
    ctx.add_tabular(out, timestamp_column="time_s", timestamp_type="epoch_seconds")


if __name__ == "__main__":
    convert.run()
```

Dockerfile:

```dockerfile
FROM python:3.12-slim
RUN pip install --no-cache-dir nominal pandas pyarrow
COPY extract.py /app/extract.py
ENTRYPOINT ["python", "/app/extract.py"]
```

Build, save, register, activate, run (on your machine):

```python
import time

from nominal.core import (
    FileExtractionInput,
    FileExtractionParameter,
    FileOutputFormat,
    IngestionJobStatus,
    NominalClient,
    wait_for_files_to_ingest,
)

client = NominalClient.from_profile("default")

# docker build --platform linux/amd64 -t my-extractor:0.1.0 .
# docker save my-extractor:0.1.0 -o my-extractor-0.1.0.tar

extractor = client.create_containerized_extractor("My Format Converter")
image = extractor.register_image(
    "my-extractor-0.1.0.tar",
    tag="0.1.0",
    inputs=[
        FileExtractionInput(
            name="Raw file", environment_variable="RAW_FILE",
            file_suffixes=["bin"], required=True,
        )
    ],
    parameters=[
        FileExtractionParameter(name="Quality threshold", environment_variable="THRESHOLD"),
    ],
    output_format=FileOutputFormat.MANIFEST,
    default_timestamp_column="time_s",
    default_timestamp_type="epoch_seconds",
)
extractor.set_active_image(image)

dataset = client.get_dataset("ri.catalog....")
job = dataset.add_containerized(
    extractor,
    sources={"RAW_FILE": "flight_042.bin"},   # keyed by environment variable
    arguments={"THRESHOLD": "0.8"},           # values are strings
)

# Waiting takes two stages: the container run, then the files it produced.
RUNNING = (IngestionJobStatus.SUBMITTED, IngestionJobStatus.QUEUED, IngestionJobStatus.IN_PROGRESS)
deadline = time.monotonic() + 3600
while job.refresh().status in RUNNING:
    if time.monotonic() > deadline:
        raise TimeoutError(f"extraction still {job.status.name} — see {job.nominal_url}")
    time.sleep(2)
if job.status is not IngestionJobStatus.COMPLETED:
    raise RuntimeError(f"extraction {job.status.name} — see {job.nominal_url}")
files, _ = wait_for_files_to_ingest(job.dataset_files())
```

The two-stage wait is not optional. `job.dataset_files()` returns only the files that exist
when it is called, and `job.as_files_ingested()` calls it once, so either one returns empty
instead of waiting if the container has not produced anything yet. See
`references/running.md` for the failure modes.

## Rules that trip people up

- **Outputs must be written under `ctx.output_dir` and declared.** The pipeline ingests only
  declared files. An undeclared file earns a warning and is dropped.
- **`manifest.json` belongs to the runtime.** Declare outputs through the `add_*` methods;
  the runtime writes the manifest when your function returns.
- **Parameters arrive as strings.** Coerce them yourself: `int(ctx.param("PARTS"))`.
- **The decorator must match the registered output format.** A mismatch fails at container
  startup, which beats emitting output the pipeline rejects.
- **Build for `linux/amd64`.** Nominal runs images on amd64, so on Apple Silicon always pass
  `--platform linux/amd64` to `docker build`. Nothing checks this: an arm64 image registers
  and activates, then fails at ingest with an exec format error. Verify before registering
  with `scripts/check_image_arch.py <tarball>` (or `docker inspect`), and run it in CI.
- **Image tags are immutable.** Re-registering an existing tag raises
  `NominalAlreadyExistsError`. Bump the tag instead.
- **Registration does not activate.** A new image runs only after
  `extractor.set_active_image(image)`.
- **Timestamp metadata resolves in order:** per-output manifest metadata → the ingest
  request's `timestamp_column`/`timestamp_type` override → the image's registered default.
  Registration requires a default. Per-output metadata takes numeric types only
  (epoch/relative, seconds through nanoseconds); ISO 8601 and custom formats must come from
  the job-level metadata.
- **Failures should fail loudly.** Any exception escaping your function exits non-zero and
  fails the ingest job. That is the designed behavior — do not swallow errors into empty
  outputs.
- **`required=True` means much less on a parameter than on an input.** A missing required
  input raises in `add_containerized` before anything uploads. A missing required parameter
  only warns at container start, then fails mid-run when `ctx.param()` reads it.
- **Never register `Relative` as the image's default timestamp type.** The `start` is set
  once and applied to every future ingest. Register an absolute default and declare
  `Relative` per output in the manifest.

## Reference files

- `references/modeling.md` — the decisions that outlive the code: inputs vs parameters,
  absolute vs relative time, what to tag, and the tagging pitfalls. Read before writing code
  for a new extractor, or when reviewing one whose shape isn't settled.
- `references/authoring.md` — the in-container runtime: context API, per-format declaration
  methods, system metadata, error semantics, local testing. Read before writing or reviewing
  extractor code.
- `references/registration.md` — Dockerfile conventions, building and saving the image,
  verifying its architecture, `register_image` arguments, image lifecycle. Read before
  registering or upgrading an image.
- `references/running.md` — triggering ingests with `add_containerized`, tracking an
  `IngestionJob`, debugging failed jobs. Read when running or troubleshooting.
- `scripts/check_image_arch.py` — exits non-zero if a `docker save` tarball isn't amd64. Run
  it before registering and in CI; nothing in the SDK or the platform checks this.
