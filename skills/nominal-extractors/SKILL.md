---
name: nominal-extractors
description: Build, test, register, and run Nominal containerized extractors — custom Docker images the Nominal platform runs during ingest to parse proprietary or unsupported file formats into datasets. Use this whenever the user mentions containerized extractors, custom extractors, nominal.experimental.extractor, @single_file_extractor / @manifest_extractor, register_image, add_containerized, `nom container`, extractor manifests, or asks how to ingest a file format Nominal doesn't natively support (binary telemetry, vendor logger output, packed/proprietary formats), how to convert files server-side during ingest, or how to debug a containerized ingest job.
---

# Nominal Containerized Extractors

A containerized extractor is a Docker image Nominal runs server-side during ingest. The
platform mounts the uploaded files into the container, runs your code, and ingests whatever
your code writes to the output directory. Once registered, anyone in the workspace can
upload files in that format — from the SDK, the `nom` CLI, or the web app — without the
parsing code on their machine.

## When to use one

Nominal parses common formats natively: `Dataset.add_tabular_data` (CSV/Parquet),
`add_mcap`, `add_video`, `add_mcap_video`, `add_avro_stream`, `add_journal_json` (logs),
`add_ardupilot_dataflash`. Write an extractor when

- the format is proprietary or unsupported — binary telemetry, packed structs, vendor logger
  output, a CSV dialect that needs preprocessing;
- it recurs, so the parsing logic belongs in one versioned place instead of on each
  engineer's laptop;
- non-developers upload the files through the web app, so the conversion has to happen
  without them running anything.

For a one-off conversion with a script you already have, convert locally and call
`dataset.add_tabular_data(...)`.

## Two surfaces, two objects

| Surface | Runs | Import |
|---|---|---|
| The extractor's own code | in the container, during ingest | `nominal.experimental.extractor` |
| Create, register, activate, trigger | on your machine | `nominal.core` via `NominalClient`, or `nom container` |

A **ContainerizedExtractor** is the stable identity uploaders select. The **ContainerImage**s
registered against it carry the execution contract — inputs, parameters, output format,
default timestamp metadata. Exactly one image is active at a time, so a new version
registers and switches over atomically.

Downstream, ingest turns each output file's columns or records into **channels**, places
samples in time from timestamp metadata, and applies **tags** that partition data within the
**dataset**.

## Lifecycle

1. **Shape the contract** — inputs vs. parameters, timestamps, tags → `references/modeling.md`
2. **Author** the function → `references/authoring.md`
3. **Test** with `extractor.run(env={...}, exit=False)`, no Docker or platform access →
   `references/authoring.md`
4. **Build** for `linux/amd64` and `docker save` → `references/registration.md`
5. **Register and activate** an image, from the SDK or `nom container` →
   `references/registration.md`
6. **Trigger ingests** and track the `IngestionJob` → `references/running.md`

Read the reference for the stage you're on before writing code — each carries contract
details that are easy to get subtly wrong from memory. Step 1 is the one people skip and the
one that's expensive to undo: inputs and parameters are fixed at registration, and the
timestamp and tag choices shape every query written against the data afterward.

## Write manifest extractors

New extractors use `@manifest_extractor`, registered with `output_format=MANIFEST`. It is the
current contract and a strict superset of the alternative: it describes each output file
individually, so one image can emit several files, mix telemetry with logs and video, and set
per-file timestamps, tag columns, and channel prefixes.

`@single_file_extractor` is the original contract, for images registered `PARQUET`, `CSV`, or
`AVRO_STREAM` — exactly one output file, declared with `ctx.set_output(path)`, with no
per-output control of any kind. Use it to maintain an image already registered that way, not
for new work, and not even when the extractor produces a single table today: declaring one
file through the manifest costs nothing, and output format is fixed at registration.

The decorator and the registered format must agree. They're checked at container startup, so
a mismatch fails the job immediately instead of emitting output the pipeline rejects.

## End-to-end

Extractor code (`extract.py`, runs inside the container):

```python
import pandas as pd

from nominal.experimental.extractor import ManifestExtractorContext, manifest_extractor


@manifest_extractor
def convert(ctx: ManifestExtractorContext) -> None:
    df = parse_proprietary(ctx.input("RAW_FILE"))          # your parsing logic
    threshold = float(ctx.get_param("THRESHOLD", "0.5"))   # params are always strings

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

Register, activate, run (on your machine):

```python
from nominal.core import (
    FileExtractionInput,
    FileExtractionParameter,
    FileOutputFormat,
    NominalClient,
)

client = NominalClient.from_profile("default")

# docker build --platform linux/amd64 -t my-extractor:0.1.0 .
# docker save my-extractor:0.1.0 -o my-extractor-0.1.0.tar
# python scripts/check_image_arch.py my-extractor-0.1.0.tar

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
    output_format=FileOutputFormat.MANIFEST,   # defaults to PARQUET — pass it explicitly
    default_timestamp_column="time_s",
    default_timestamp_type="epoch_seconds",
)
extractor.set_active_image(image)

dataset = client.get_dataset("ri.catalog....")
job = dataset.add_containerized(
    extractor,
    sources={"RAW_FILE": "flight_042.bin"},   # keyed by environment variable
    arguments={"THRESHOLD": "0.8"},
)
```

Then wait in two stages — poll `job.refresh().status` out of the running set, and only then
`wait_for_files_to_ingest(job.dataset_files())`. Both are required: `dataset_files()` returns
the files that exist when it is called, so running it before the job is terminal sees an
empty list and waits for nothing — a green "wait" over zero outputs. `references/running.md`
has the loop to copy and the failure modes.

## Traps

- **Outputs must be written under `ctx.output_dir` and declared.** Only declared files are
  ingested; an undeclared one earns a warning and is dropped. `manifest.json` belongs to the
  runtime — declare through the `add_*` methods and it writes the manifest for you.
- **`output_format` defaults to `PARQUET`.** Omit it while writing a manifest extractor and
  you register the single-file contract, after which every run fails at startup.
- **Parameters arrive as strings.** Coerce them: `int(ctx.get_param("PARTS", "2"))`.
- **Build for `linux/amd64`.** Nothing checks this — an arm64 image (the default on Apple
  Silicon) registers, activates, reports READY, then fails at ingest with an exec format
  error. Verify with `scripts/check_image_arch.py <tarball>` or `docker inspect`, in CI.
- **Image tags are immutable**, and registration does not activate. Re-registering a tag
  raises `NominalAlreadyExistsError`; a new image runs only after `set_active_image`.
- **Timestamp metadata is layered**, per output file: manifest → ingest request → the image's
  registered default, which registration requires. Per-output metadata is numeric-only, so
  ISO 8601 and custom formats have to come from the job level, and `Relative` must never be an
  image default — its `start` would apply to every future ingest. Details in `authoring.md`.
- **`required=True` is much weaker on a parameter than on an input.** A missing required
  input raises in `add_containerized` before anything uploads; a missing required parameter
  only warns at container start, then fails mid-run when `ctx.param()` reads it.
- **Fail loudly.** Any exception escaping your function exits non-zero and fails the job,
  which is the designed behavior. An empty dataset under a green job is far worse than a red
  one, so never swallow parse errors to keep going.
- **Container logs are capped at 1 MiB per job.** A chatty extractor can push its own
  traceback out of the captured log. Log decisions and counts, not rows.

## Reference map

| File | Read it when |
|---|---|
| `references/modeling.md` | shaping a new extractor: inputs vs. parameters, absolute vs. relative time, what to tag |
| `references/authoring.md` | writing or reviewing extractor code: context API, per-format declarations, errors, local testing |
| `references/registration.md` | building, registering, activating, upgrading images — SDK and `nom container` CLI |
| `references/running.md` | triggering ingests, tracking jobs, debugging a failure |
| `scripts/check_image_arch.py` | before every registration and in CI: exits non-zero if a `docker save` tarball isn't amd64 |
