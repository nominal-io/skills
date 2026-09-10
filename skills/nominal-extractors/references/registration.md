# Building and registering images

Reuse the project's stable extractor, release convention, configured authentication and
existing registration code. Inspect the live extractor and contract before changing an
existing deployment. Create an extractor only when a new identity is intended; uploaders
select that stable identity while images change underneath it.

Keep the executable contract in a checked-in Python registration script by default, with
short rationale and commands in the existing README. Deployment inputs follow the project's
existing convention; environment variables below are illustrative. Do not add a local state
registry or ask for credentials in chat.

## Choose the release identity

These are three different uses of “tag”:

| Tag | Purpose |
|---|---|
| Local Docker tag, e.g. `my-extractor:0.3.0-g1a2b3c4-b42` | Selects the local image to inspect and save. |
| Nominal registration tag, e.g. `0.3.0-g1a2b3c4-b42` | Immutable version under the stable extractor. |
| Telemetry tags, e.g. `{"stand": "Stand-A"}` | Dimensions on ingested data; not image-version metadata. |

Prefer existing semver or CI release IDs. If introducing a scheme, a source revision plus a
unique build ID, or an intentionally assigned manual version, identifies distinct builds.
The example `0.3.0-g1a2b3c4-b42` is illustrative, not mandatory. A source SHA alone does not
prove reproducibility: base images, dependencies and build inputs can change. Do not use
movable `latest`/`prod` aliases as immutable registration versions or append random suffixes
to make retries pass.

## Build and verify amd64

Use an ordinary entrypoint; Nominal supplies runtime configuration through the environment:

```dockerfile
FROM python:3.12-slim
RUN pip install --no-cache-dir nominal pandas pyarrow
COPY extract.py /app/extract.py
ENTRYPOINT ["python", "/app/extract.py"]
```

This minimal Dockerfile illustrates structure. Pin the base image and dependencies through
the project's normal lock/build convention before relying on repeatable releases. Include
all parser libraries; the container does not inherit the developer's environment.

Reuse the base image the project already builds on. If nothing is established and CVE
posture matters to the project or its operators, raise
[Chainguard's hardened images](https://hub.docker.com/u/chainguard) once, at this stage: they
are low-to-zero-CVE drop-ins for the common language runtimes, and swapping the base after a
release costs a new image version and another registration. Take the answer as settled; do
not re-ask per build.

Their runtime images are distroless — no shell, no package manager — so install into the
`-dev` variant and copy the result across:

```dockerfile
FROM chainguard/python:latest-dev@sha256:<digest> AS build
RUN pip install --no-cache-dir --user nominal pandas pyarrow

FROM chainguard/python:latest@sha256:<digest>
COPY --from=build /home/nonroot/.local /home/nonroot/.local
COPY extract.py /app/extract.py
ENTRYPOINT ["python", "/app/extract.py"]
```

Two consequences worth stating before someone adopts this. The public catalog carries only
`latest` and `latest-dev`, no version tags, so pin by digest or the interpreter moves under
you — and pin both stages to the same release, or the builder's `site-packages` lands on a
path the runtime's Python does not read. These images also run as UID 65532 rather than root:
confirm the parser can still write its outputs. A local `docker run` is weaker evidence than
it looks here, since Docker Desktop remaps bind-mount ownership where a Linux host would not.

```sh
docker build --platform linux/amd64 -t my-extractor:0.3.0-g1a2b3c4-b42 .
docker image inspect my-extractor:0.3.0-g1a2b3c4-b42 \
  --format 'os={{.Os}} arch={{.Architecture}} variant={{.Variant}}'
# want:  os=linux arch=amd64 variant=
# wrong: os=linux arch=arm64 variant=v8   (an Apple Silicon build — rebuild, don't register)
docker save my-extractor:0.3.0-g1a2b3c4-b42 -o my-extractor-0.3.0-g1a2b3c4-b42.tar
```

Read that line rather than trusting `--platform`: an earlier native build can still own the
tag, and a Dockerfile pinning `FROM --platform=...` overrides the flag. `register_image` does
not check either — an arm64 image registers, reports READY, then fails at ingest with an exec
format error. Rebuild on any other `arch`, with `--no-cache` if the build already claimed
success. Save one amd64 image; Nominal receives an archive, not a registry it can negotiate a
platform with, so do not assume it selects amd64 out of a multi-platform archive.

To check an archive built somewhere else — a CI artifact, or a tarball handed to you — load
it and inspect the tag `docker load` reports:

```sh
docker load --input my-extractor-0.3.0-g1a2b3c4-b42.tar
docker image inspect my-extractor:0.3.0-g1a2b3c4-b42 --format 'arch={{.Architecture}}'
```

`register_image` uploads that archive directly to Nominal; no external registry or
`docker push` is needed.

## Register the contract in code

Adapt the contract to the agreed parser. This example assumes an existing extractor and
configured Nominal profile; importing the script performs no platform mutations:

```python
import os

from nominal.core import (
    FileExtractionInput, FileExtractionParameter, FileOutputFormat, NominalClient,
)


def main() -> None:
    client = NominalClient.from_profile(os.environ["NOMINAL_PROFILE"])
    extractor = client.get_containerized_extractor(os.environ["EXTRACTOR_RID"])
    image = extractor.register_image(
        os.environ["IMAGE_ARCHIVE"],
        tag=os.environ["IMAGE_VERSION"],
        inputs=[
            FileExtractionInput(
                name="Raw file",
                environment_variable="RAW_FILE",
                description="ACME logger .bin capture",
                file_suffixes=["bin"],
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
    print(image.rid)


if __name__ == "__main__":
    main()
```

With `EXTRACTOR_RID` and the configured `NOMINAL_PROFILE` supplied through the existing
deployment convention:

```sh
IMAGE_ARCHIVE=my-extractor-0.3.0-g1a2b3c4-b42.tar \
IMAGE_VERSION=0.3.0-g1a2b3c4-b42 python register_image.py
```

Input and parameter environment-variable names must be distinct across both lists and match
parser lookups and callers' `sources`/`arguments`. Suffixes aid discovery, not validation;
required parameters still need parser-side validation. See [modeling](modeling.md).

**Registration defaults to `PARQUET`.** Pass `MANIFEST` explicitly for `@manifest_extractor`;
`@single_file_extractor` requires matching `PARQUET`, `CSV`, or `AVRO_STREAM`. Only these four
formats can be registered (`REGISTERABLE_OUTPUT_FORMATS`). A mismatch fails at startup.
Timestamp defaults are required; use the authoritative
[timestamp metadata contract](authoring.md#timestamp-metadata-contract) for types, precedence
and capture-specific starts.

Keep provenance in usual build output or existing release notes: source revision, build ID
and archive checksum, registered contract, version and returned image RID. An archive checksum
identifies those archive bytes; it is not an OCI image digest. Image objects do not offer
arbitrary telemetry-style tags for provenance. Do not create a separate state/config registry.

If registration raises `NominalAlreadyExistsError`, query
`extractor.search_container_images(tag=version)` and inspect the existing image's contract.
Reuse it only when release evidence establishes the same artifact and contract; a matching
source revision or version string is insufficient. Otherwise choose a deliberate new release
identity. Do not delete/recreate the old version or blindly retry with random suffixes.

For a new stable identity, `client.create_containerized_extractor(name, description=...)`
returns the extractor. Existing ones are retrieved with `get_containerized_extractor(rid)` or
found with `search_containerized_extractors()`. Preserve that RID in the project's existing
deployment convention.

## Activate within the authorized scope

SDK registration attaches an image; it does not activate it. Before activation, fetch the
live target extractor, inspect its active image/contract, and identify the prior image RID
for rollback. Confirm the intended environment and the scope already authorized; registration
alone is not evidence of authorization to switch a production extractor.

```python
extractor = client.get_containerized_extractor(extractor_rid)
prior_image = extractor.active_image
image = client.get_container_image(image_rid)
extractor = extractor.set_active_image(image)
assert client.get_containerized_extractor(extractor_rid).active_image.rid == image.rid
```

`set_active_image` waits for READY first; `poll_until_ready=False` raises if the image is not
ready. Future ingests use the new image; in-flight jobs finish on their starting image.
Rollback means reactivating the known prior image, then verifying live state. It changes
future jobs and does not repair data already ingested. A canary requires a real test extractor
or environment with the candidate active; ingestion has no arbitrary image override.

Contract changes require both sides: update callers for renamed inputs/parameters, decorators
for changed output modes, and parser/request metadata for changed timestamps. Activation does
not migrate old data. Validate a representative ingest using [running](running.md).

## Existing CLI/CI workflows

Preserve projects already using `nom container` and its checked-in config JSON. It is an
optional contract representation, not the only version-controlled choice. Flags override the
config; unknown keys are rejected. Validate before upload:

```sh
nom container extractor validate-config extractor-config.json
nom container extractor register-image -r "$EXTRACTOR_RID" \
    -f my-extractor-0.3.0-g1a2b3c4-b42.tar -t 0.3.0-g1a2b3c4-b42 -c extractor-config.json
```

Validation is local and needs no credentials. Registration prints the image RID on stdout,
status on stderr, and waits for READY by default (`--no-wait` skips waiting). Activation is
separate: `nom container extractor set-active-image -r "$EXTRACTOR_RID" -i "$IMAGE_RID"`.
The CLI does not trigger containerized ingests; use the SDK or web app.

For live inspection use `extractor.active_image`, `extractor.search_container_images(...)`,
`client.search_container_images(...)` or `client.get_container_image(rid)`. Image processing
statuses are PENDING, READY and FAILED; `image.poll_until_ready()` handles asynchronous
processing. `image.delete()` fails while active and is not a version-retry strategy.
Extractor `update`, `archive` and `unarchive` manage the stable identity; archive hides it from
search and rejects new ingests. On resume, query Nominal rather than trusting a local snapshot.
