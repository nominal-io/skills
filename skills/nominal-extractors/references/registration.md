# Building and registering images

Everything here runs on your machine or in CI, against the platform — through
`NominalClient`, or through the `nom container` CLI, which covers the same lifecycle.

## Dockerfile

An ordinary image whose entrypoint runs your extractor script:

```dockerfile
FROM python:3.12-slim
RUN pip install --no-cache-dir nominal pandas pyarrow
COPY extract.py /app/extract.py
ENTRYPOINT ["python", "/app/extract.py"]
```

Install `nominal` plus your format libraries, and pin versions for reproducible rebuilds. No
CMD arguments and no shell wrapper are needed — all configuration arrives through the
environment. Keep the image lean: the whole thing is uploaded as a tarball on every
registration.

## Build and save — amd64 is required

```sh
docker build --platform linux/amd64 -t my-extractor:0.1.0 .
docker save my-extractor:0.1.0 -o my-extractor-0.1.0.tar
```

`register_image` uploads that `docker save` tarball. There is no `docker push` and no
external registry — Nominal hosts the image itself.

Nothing checks the architecture. An arm64 image (the default on Apple Silicon) registers,
activates, and reports READY, then fails at ingest with an exec format error — surfacing in a
job log long after the mistake, looking like a broken extractor rather than a missing build
flag. Verify before registering, and keep the check in CI:

```sh
docker inspect my-extractor:0.1.0 --format '{{.Architecture}}'   # want: amd64
python scripts/check_image_arch.py my-extractor-0.1.0.tar        # or from the tarball alone
```

`scripts/check_image_arch.py` reads the architecture out of the tarball and exits non-zero
when it isn't amd64, so it drops into a pipeline ahead of the registration step. It handles
both layouts `docker save` produces (OCI `index.json` + `blobs/`, and the legacy
`manifest.json` plus per-image config), and exits 2 when it can't parse the tarball — which
means *check by hand*, not *proceed*.

## Create the extractor (once)

```python
extractor = client.create_containerized_extractor(
    "My Format Converter",
    description="Parses ACME vX binary telemetry into channels",
)
print(extractor.rid)   # save this; it's the stable handle
```

Images come and go underneath it. Retrieve it later with
`client.get_containerized_extractor(rid)` or `client.search_containerized_extractors()`.

## Register an image

```python
from nominal.core import FileExtractionInput, FileExtractionParameter, FileOutputFormat

image = extractor.register_image(
    "my-extractor-0.1.0.tar",
    tag="0.1.0",
    inputs=[
        FileExtractionInput(
            name="Raw file",                    # display name shown to uploaders
            environment_variable="RAW_FILE",    # how your code reads it
            description="ACME logger .bin capture",
            file_suffixes=["bin"],              # accepted suffixes; empty = any file
            required=True,
        ),
    ],
    parameters=[
        FileExtractionParameter(
            name="Quality threshold",
            environment_variable="THRESHOLD",
            description="Drop samples with quality below this value (0-1)",
            required=False,
        ),
    ],
    output_format=FileOutputFormat.MANIFEST,
    default_timestamp_column="time_s",
    default_timestamp_type="epoch_seconds",
)
```

- **`tag`** — immutable. Registering an already-used tag raises `NominalAlreadyExistsError`,
  so version tags (`0.1.0`, a git short SHA) and register a new one for every code change.
- **`inputs` / `parameters`** — the `environment_variable` is the contract key everywhere:
  how the code reads the value (`ctx.input("RAW_FILE")`) and how ingest requests supply it
  (`sources={"RAW_FILE": path}`). Each must be distinct across inputs and parameters. See
  `modeling.md` for which values belong in which — and for why `required` means much less on
  a parameter than on an input.
- **`output_format`** — must match the decorator (`MANIFEST` ↔ `@manifest_extractor`;
  `PARQUET`/`CSV`/`AVRO_STREAM` ↔ `@single_file_extractor`). **It defaults to `PARQUET`**, so
  a manifest extractor has to pass it explicitly; omit it and you register the single-file
  contract, after which every run fails at container startup. Only those four register — the
  backend has no reader for the other formats, so `register_image` rejects them up front
  (`REGISTERABLE_OUTPUT_FORMATS`).
- **`default_timestamp_column` / `default_timestamp_type`** — required. Stored as the image's
  `default_timestamp_metadata`, the last stop in the resolution order (`authoring.md`), and it
  accepts the full range of types where per-output metadata doesn't. `ts.Relative` is accepted
  but is almost always wrong as a *default*: its `start` would apply to every future ingest.

## Activate it

Registration attaches the image but does not change what runs:

```python
extractor = extractor.set_active_image(image)
```

This is the atomic switch: ingests started after it run the new image, and in-flight jobs
finish on the image they started with. `set_active_image` polls the image to `READY` first
(`poll_until_ready=False` raises immediately if it isn't).

## The same thing from CI: `nom container`

The CLI covers the whole lifecycle except triggering ingests, which stays in the SDK or the
web app. `register-image` prints the new image RID on stdout with status messages on stderr,
so it composes:

```sh
IMAGE_RID=$(nom container extractor register-image -r "$EXTRACTOR_RID" \
    -f my-extractor.tar -t "$(git rev-parse --short HEAD)" -c extractor-config.json)
nom container extractor set-active-image -r "$EXTRACTOR_RID" -i "$IMAGE_RID"
```

`register-image` waits for `READY` by default (`--no-wait` to skip), and the contract comes
from a config JSON checked in beside the Dockerfile — which is the real reason to prefer the
CLI in CI, since it keeps the contract in version control instead of in a script:

```json
{
  "tag": "0.1.0",
  "output_format": "manifest",
  "default_timestamp_column": "time_s",
  "default_timestamp_type": "epoch_seconds",
  "inputs": [
    {
      "name": "Raw file",
      "environment_variable": "RAW_FILE",
      "description": "ACME logger .bin capture",
      "file_suffixes": ["bin"],
      "required": true
    }
  ],
  "parameters": [
    {"name": "Quality threshold", "environment_variable": "THRESHOLD", "required": false}
  ]
}
```

Keys are the snake_case `FileExtractionInput` / `FileExtractionParameter` fields, and every
top-level key is optional — flags override the file, and `--tag`, `--timestamp-column`,
`--timestamp-type`, `--output-format` can supply anything it omits. Unknown keys are
rejected rather than ignored, so a typo fails instead of silently dropping an input.

`nom container extractor validate-config extractor-config.json` runs exactly the validation
`register-image` does before uploading — unknown keys, unparseable entries, empty names,
duplicate environment variables, unknown timestamp types and output formats — without
contacting Nominal. It needs no credentials, so it belongs in the same CI job that builds the
image, alongside `check_image_arch.py`.

The rest: `nom container extractor create | get | search | update | archive | unarchive`, and
`nom container image get | search | delete`. `search` takes `--format csv` for scripting.

## Image lifecycle

- **Statuses**: `PENDING` (processing) → `READY` or `FAILED`. Current backends return images
  `READY` from `register_image` directly; `image.poll_until_ready()` covers asynchronous ones.
- **Upgrade**: build a new tarball → `register_image(tag="0.2.0", ...)` → `set_active_image`.
  The old image stays registered, so rolling back is re-activating it.
- **Inspect**: `extractor.active_image` is what runs (or `None` — ingests fail until one is
  activated), and it carries the live contract, so `extractor.active_image.inputs` is the
  authoritative answer to "what keys does `sources` need?".
  `extractor.search_container_images(tag=..., status=...)` and
  `client.search_container_images(...)` list images; `client.get_container_image(rid)` fetches
  one.
- **Delete**: `image.delete()`, which fails server-side while an extractor has it active.
- **Extractor-level**: `extractor.update(name=..., description=...)`; `extractor.archive()`
  hides it from search and rejects new ingests; `extractor.unarchive()` reverses that.

## When a new version changes the contract

Not just the code — update both sides:

- new or renamed input/parameter environment variables → update every caller's `sources` and
  `arguments`;
- output format change (single-file ↔ manifest) → change the decorator too, or every run
  fails at startup;
- timestamp column or type change → the registered default is per-image, so the new
  registration carries it; also update any per-output metadata in the code.
