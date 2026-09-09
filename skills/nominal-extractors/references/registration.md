# Building and registering extractor images

Everything here runs on your machine, against the platform, via `NominalClient`.

## Dockerfile conventions

The image is an ordinary Docker image whose entrypoint runs your extractor script:

```dockerfile
FROM python:3.12-slim
RUN pip install --no-cache-dir nominal pandas pyarrow
COPY extract.py /app/extract.py
ENTRYPOINT ["python", "/app/extract.py"]
```

- Install `nominal` (the runtime) plus your format libraries. Pin versions for
  reproducible rebuilds.
- No CMD arguments, no shell wrapper needed — all configuration arrives through the
  environment.
- Keep the image lean (slim base, `--no-cache-dir`): the whole image is uploaded as a
  tarball on every registration.

## Build and save — linux/amd64 is required

Nominal runs extractor images on amd64. On Apple Silicon (or any non-amd64 host) an image
built without `--platform` will fail at runtime on the platform, so always build:

```sh
docker build --platform linux/amd64 -t my-extractor:0.1.0 .
docker save my-extractor:0.1.0 -o my-extractor-0.1.0.tar
```

`register_image` uploads the `docker save` tarball — not a registry reference. There is no
docker push and no external registry involved; Nominal hosts the image in its own registry.

### Verify the architecture before registering

Registration does not check it. An arm64 image registers, activates, and reports READY, then
fails at ingest with an exec format error, so the mistake surfaces in a job log long after
the upload and looks like a broken extractor rather than a wrong build flag. Confirm it
before registering, and run the check in CI so a forgotten `--platform` never reaches the
platform:

```sh
# with the image still in the local daemon
docker inspect my-extractor:0.1.0 --format '{{.Architecture}}'   # want: amd64

# or from the tarball alone, e.g. in CI where the artifact is all you have
python scripts/check_image_arch.py my-extractor-0.1.0.tar
```

`scripts/check_image_arch.py` reads the architecture out of the tarball and exits non-zero
when it isn't amd64, so it drops into a pipeline before the registration step. It handles
both layouts `docker save` produces: the OCI layout (`index.json` + `blobs/`) and the legacy
one (`manifest.json` plus a config per image). It exits 2 when it cannot parse the tarball,
which means *check by hand*, not *proceed*.

Keep this check in your build, not in the SDK. `register_image` does not inspect the tarball
today, so nothing server-side catches it for you.

## Create the extractor (once)

```python
from nominal.core import NominalClient

client = NominalClient.from_profile("default")
extractor = client.create_containerized_extractor(
    "My Format Converter",
    description="Parses ACME vX binary telemetry into channels",
)
print(extractor.rid)   # save this; it's the stable handle
```

The extractor is the stable identity users select when ingesting; images come and go
underneath it. Retrieve later with `client.get_containerized_extractor(rid)` or
`client.search_containerized_extractors()`.

## Register an image against it

```python
from nominal.core import (
    FileExtractionInput,
    FileExtractionParameter,
    FileOutputFormat,
)

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

Argument notes:

- **`tag`** — immutable. Registering an already-used tag raises
  `NominalAlreadyExistsError`; version your tags (`0.1.0`, `0.2.0`, ...) and register a
  new one for every code change.
- **`inputs`** — one `FileExtractionInput` per file the container consumes. The
  `environment_variable` is the contract key everywhere: it's how the extractor code reads
  the file (`ctx.input("RAW_FILE")`) and how ingest requests supply it
  (`sources={"RAW_FILE": path}`). `required=True` makes ingest requests fail fast when the
  input is missing; an optional input simply isn't among the run's inputs when omitted.
- **`parameters`** — scalar knobs, delivered as environment-variable strings. Same
  name/env-var duality as inputs, but a weaker `required`: unlike a required input, a
  missing required parameter is not checked before the ingest starts. See `modeling.md` for
  which values belong here rather than in `inputs` or in the image itself.
- **`output_format`** — must match the decorator in the code (`MANIFEST` ↔
  `@manifest_extractor`; `PARQUET`/`CSV`/`AVRO_STREAM` ↔ `@single_file_extractor`).
  **It defaults to `PARQUET`, so a manifest extractor has to pass it explicitly** — follow the
  manifest-first guidance and omit the argument and you register the single-file contract, after
  which every run fails at container startup on the mismatch described below.
  Only those four register: the backend can't currently ingest the other proto formats,
  so `register_image` rejects them up-front (`REGISTERABLE_OUTPUT_FORMATS`).
- **`default_timestamp_column` / `default_timestamp_type`** — required. This is the
  image's `default_timestamp_metadata`: the fallback timestamp encoding for outputs that
  don't carry their own, and the last stop in the resolution order (per-output manifest
  metadata → ingest request override → this default). Accepts the full range of types:
  string literals (`"epoch_seconds"`, `"iso_8601"`, ...) or typed forms (`ts.Epoch`,
  `ts.Iso8601`, `ts.Custom(format=...)`, `ts.Relative`). `ts.Relative` is accepted here but
  is almost always wrong as a *default* — its `start` would apply to every future ingest;
  see `modeling.md`.

## Activate the image

Registration attaches the image to the extractor but does not change what runs:

```python
extractor = extractor.set_active_image(image)
```

`set_active_image` polls the image to `READY` before activating (pass
`poll_until_ready=False` to raise immediately if it isn't). This is the atomic switch —
ingests started after this run the new image.

## Image lifecycle

- **Statuses**: `PENDING` (processing) → `READY` or `FAILED`. Current backends return
  images `READY` from `register_image` directly; `image.poll_until_ready()` covers
  asynchronous backends.
- **Upgrade flow**: build new tarball → `register_image(tag="0.2.0", ...)` →
  `set_active_image`. The old image stays registered; roll back by re-activating it.
- **Inspect**: `extractor.search_container_images(tag=..., status=...)` lists images
  registered against this extractor; `client.get_container_image(rid)` fetches one.
  `extractor.active_image` is the currently-active one (or None — ingests fail until one
  is activated).
- **Delete**: `image.delete()` — fails server-side while an extractor references it as
  active.
- **Extractor updates**: `extractor.update(name=..., description=...)`;
  `extractor.archive()` hides it from search and rejects new ingests;
  `extractor.unarchive()` reverses that.

## Contract-change checklist

When a new image version changes the *contract*, not just the code, update both sides:

- New or renamed input/parameter env vars: update every caller's `sources` and `arguments`.
- Output format change (single-file ↔ manifest): change the decorator too. The runtime fails
  at startup if they disagree.
- Timestamp column or type change: update the registered default, which is per-image so the
  new registration carries it, plus any per-output metadata in the code.
