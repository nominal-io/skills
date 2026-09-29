# Building and registering images

Reuse the project's stable extractor, release convention, configured authentication and
existing registration code. Inspect the live extractor and contract before changing an
existing deployment. Create an extractor only when a new identity is intended; uploaders
select that stable identity while images change underneath it.

Registration runs on a developer or CI machine with the Python SDK or the `nom` CLI, whatever
language the extractor itself uses. Keep the executable contract in one checked-in place: the
decorators plus a registration script for Python extractors, and a `nom` config JSON or a
registration script with explicit lists for other languages. Put short rationale and commands
in the existing README. Deployment inputs follow the project's existing convention;
environment variables below are illustrative. Do not add a local state registry or ask for
credentials in chat.

## Contents

- [Choose the release identity](#choose-the-release-identity)
- [Write the Dockerfile](#write-the-dockerfile)
  - [Choose the base image](#choose-the-base-image)
- [Build and verify amd64](#build-and-verify-amd64)
- [Register the contract](#register-the-contract)
  - [Python extractors: generate it from the declarations](#python-extractors-generate-it-from-the-declarations)
  - [Other languages: state the contract explicitly](#other-languages-state-the-contract-explicitly)
- [Exit-code fallbacks](#exit-code-fallbacks)
- [Identity, discovery and provenance](#identity-discovery-and-provenance)

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

## Write the Dockerfile

These rules hold in every language:

- Use an ordinary entrypoint with an absolute path; Nominal supplies configuration through the
  environment, not arguments.
- Install dependencies from the project's own manifest and lockfile (`uv.lock`,
  `requirements.txt`, `package-lock.json`, `go.sum`, `Cargo.lock`, ...). A hand-listed install
  in the Dockerfile is a second, unpinned dependency set that drifts from what the parser was
  tested against. With no convention established for Python, propose `uv` and a lockfile.
- Pin the base image and tool versions; a source SHA over an unpinned base does not describe a
  reproducible release. Include every parser library, since the container inherits nothing from
  the developer's environment.
- Install everything outside `/home` and ship files readable by any UID. The platform's
  [runtime environment](contract.md#runtime-environment) runs a different non-root user and
  mounts an empty `/home`, so dependencies under the home directory (`pip install --user`,
  `~/.local`, `~/.venv`, a toolchain cache) vanish at runtime, surfacing as
  `ModuleNotFoundError` or a missing library the image demonstrably contains. `$OUTPUT_DIR`
  needs no ownership or permission setup.
- Minimal bases may lack a shell, CA certificates or timezone data; include what the parser
  needs, such as tzdata when converting local times.

For Python with a `pyproject.toml` and `uv.lock`:

```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY extract.py ./
ENTRYPOINT ["/app/.venv/bin/python", "/app/extract.py"]
```

With a `requirements.txt`, install from that file instead — `RUN uv pip install --system
--no-cache -r requirements.txt`, or the project's own pip invocation — and keep the plain
`python` entrypoint. Other interpreted runtimes such as Node, Ruby or the JVM follow the same
pattern: install from the lockfile in a build stage, copy the app and its dependencies into the
runtime image, and give an absolute entrypoint for the runtime binary.

A compiled parser needs only its binary and the libraries it links. Build in the toolchain
image, then copy into a minimal runtime that matches the linkage: a static binary into a
static base, a glibc-linked one into a glibc base such as Debian slim or Chainguard's
`glibc-dynamic`. For example, with Go:

```dockerfile
FROM golang:1.23-bookworm@sha256:<digest> AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -o /out/extract ./cmd/extract

FROM chainguard/static:latest@sha256:<digest>
COPY --from=build /out/extract /usr/local/bin/extract
ENTRYPOINT ["/usr/local/bin/extract"]
```

Rust, C++ and others follow the same shape: `cargo build --locked --release` or the project's
build, with a pinned toolchain and the lockfile honored.

### Choose the base image

Reuse the base image the project already builds on. If nothing is established and CVE posture
matters to the project or its operators, raise
[Chainguard's hardened images](https://hub.docker.com/u/chainguard) once, at this stage: they
are low-to-zero-CVE drop-ins for the common language runtimes, and swapping the base after a
release costs a new image version and another registration. Take the answer as settled; do
not re-ask per build.

Their runtime images are distroless — no shell, no package manager, and their own entrypoint,
working directory and user, which `docker image inspect` shows — so install in the `-dev`
variant and copy the result across:

```dockerfile
FROM chainguard/python:latest-dev@sha256:<digest> AS build
USER root
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --python /usr/bin/python

FROM chainguard/python:latest@sha256:<digest>
COPY --from=build /app/.venv /app/.venv
COPY extract.py /app/extract.py
ENTRYPOINT ["/app/.venv/bin/python", "/app/extract.py"]
```

`USER root` is needed because the `-dev` variant is itself non-root and the install writes
outside the home directory. `UV_PYTHON_DOWNLOADS=never` with an explicit `--python` keeps
`uv` on the base image's interpreter; left to itself it may fetch its own, and the venv then
points at a path the runtime stage does not have. The public catalog carries only `latest`
and `latest-dev`, no version tags, so pin by digest — and pin both stages to the same
release, or the venv's interpreter symlink and `site-packages` disagree with the runtime's
Python. `docker buildx imagetools inspect <image>:<tag>` prints the digest to pin.

## Build and verify amd64

```sh
docker build --platform linux/amd64 -t my-extractor:0.3.0-g1a2b3c4-b42 .
docker image inspect my-extractor:0.3.0-g1a2b3c4-b42 \
  --format 'os={{.Os}} arch={{.Architecture}} variant={{.Variant}}'
# want:  os=linux arch=amd64 variant=
# wrong: os=linux arch=arm64 variant=v8   (an Apple Silicon build — rebuild, don't register)
docker save my-extractor:0.3.0-g1a2b3c4-b42 -o my-extractor-0.3.0-g1a2b3c4-b42.tar
```

Read that line rather than trusting `--platform`: an earlier native build can still own the
tag, and a Dockerfile pinning `FROM --platform=...` overrides the flag. A cross-compiled binary
must also target amd64 (`GOARCH=amd64`, an `x86_64-unknown-linux-*` Rust target); an arm64
binary inside an amd64-labelled image passes the inspect check and still fails at exec.
Registration does not check either — an arm64 image registers, reports READY, then fails at
ingest with an exec format error. Rebuild on any other `arch`, with `--no-cache` if the build
already claimed success. Save one amd64 image; Nominal receives an archive, not a registry it
can negotiate a platform with, so do not assume it selects amd64 out of a multi-platform
archive. Docker Desktop's containerd image store may write an OCI index even for a
one-platform build; `docker image ls --tree` shows whether anything besides linux/amd64 (and
build attestations) is in it. Run the [conformance check](contract.md#check-conformance-locally)
on the built image before registering it.

To check an archive built somewhere else — a CI artifact, or a tarball handed to you — load
it and inspect the tag `docker load` reports:

```sh
docker load --input my-extractor-0.3.0-g1a2b3c4-b42.tar
docker image inspect my-extractor:0.3.0-g1a2b3c4-b42 --format 'arch={{.Architecture}}'
```

Registration uploads that archive directly to Nominal; no external registry or `docker push`
is needed.

## Register the contract

Every path below assumes an existing extractor and a configured Nominal profile, and importing
its script performs no platform mutations. The same rules hold on all of them:

- **Output format defaults to `PARQUET`** unless given; register `MANIFEST` for new work. Only
  `MANIFEST`, `PARQUET`, `CSV` and `AVRO_STREAM` can be registered. A mismatch with the code
  fails at startup when the code checks `_NOMINAL_OUTPUT_FORMAT`, and otherwise at ingest.
- Input and parameter environment-variable names must be distinct across both lists and match
  the code and callers' `sources`/`arguments`.
- Timestamp defaults are required; see the
  [timestamp metadata precedence](contract.md#timestamp-metadata-precedence) for types and
  where capture-specific starts belong.

### Python extractors: generate it from the declarations

`registration_kwargs()` exports the decorated entrypoint's contract, so registration cannot
drift from the code:

```python
import os

from nominal.core import NominalClient

from extract import convert  # the decorated entrypoint; importing it runs nothing


def main() -> None:
    client = NominalClient.from_profile(os.environ["NOMINAL_PROFILE"])
    extractor = client.get_containerized_extractor(os.environ["EXTRACTOR_RID"])
    image = extractor.register_image(
        os.environ["IMAGE_ARCHIVE"],
        tag=os.environ["IMAGE_VERSION"],
        **convert.registration_kwargs(),
    )
    print(image.rid)


if __name__ == "__main__":
    main()
```

| Declaration | `register_image` argument |
|---|---|
| `@input` | `inputs`: name, environment variable, description, suffixes, requiredness |
| `@parameter` | `parameters`: name, environment variable, description, requiredness |
| `@error` | `exit_code_mappings`: exit status, code, static `message`, retryability |
| Outer decorator | `output_format`, `default_timestamp_column`, `default_timestamp_type` |

The export reads only declarations: it does not run converters or extraction, read the
environment or touch the network. It raises `ValueError` unless both timestamp defaults are
declared, every `@error` has a `message=`, and a single-file extractor states its
`output_format`. Converter types and defaults are not registered. A partially migrated
extractor exports only its decorated arguments, so keep complete manual metadata until every
lookup is declared. `catalog_manifest()` exports the format of Nominal's own first-party
extractor catalog; customer extractors register directly as shown here.

### Other languages: state the contract explicitly

With the CLI, check in a config JSON using snake_case `FileExtractionInput` and
`FileExtractionParameter` fields:

```json
{
  "inputs": [
    {"name": "Raw file", "environment_variable": "RAW_FILE", "description": "ACME logger .bin capture", "file_suffixes": ["bin"], "required": true}
  ],
  "parameters": [
    {"name": "Quality threshold", "environment_variable": "THRESHOLD", "description": "Drop samples below this quality, 0-1 (default 0.9)", "required": false}
  ],
  "output_format": "manifest",
  "default_timestamp_column": "time_ns",
  "default_timestamp_type": "epoch_nanoseconds"
}
```

```sh
nom container extractor validate-config extractor-config.json
IMAGE_RID=$(nom container extractor register-image -r "$EXTRACTOR_RID" \
    -f my-extractor-0.3.0-g1a2b3c4-b42.tar -t 0.3.0-g1a2b3c4-b42 -c extractor-config.json)
```

- `nom` installs as an ordinary tool (`uv tool install nominal` or `pipx install nominal`) and
  needs no Python knowledge to run.
- `validate-config` is local and needs no credentials, so run it in CI, together with a test in
  the extractor's language that reads the checked-in config and compares it with the code's
  constants.
- Flags override the config and unknown keys are rejected, but reserved variable names and
  suffix form go unchecked: write suffixes without a leading dot (`bin`, `csv.gz`), as
  file-extension search expects, and keep clear of the
  [reserved names](contract.md#metadata-variables).
- `default_timestamp_type` accepts `iso_8601` and the `epoch_*` units.
- `register-image` prints the image RID on stdout and status on stderr, and waits for READY
  unless `--no-wait` is passed.
- The config has no exit-code mappings, and `nom container extractor create` sets no labels or
  properties. That is acceptable when every non-zero exit path, including a top-level crash
  handler, writes the termination log; otherwise register the fallbacks, and any labels, with
  the SDK script below.

With the SDK, pass the same contract as explicit lists; Python here is only the deployment
tool:

```python
from nominal.core import ExitCodeMapping, FileExtractionInput, FileExtractionParameter, FileOutputFormat

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
            description="Drop samples below this quality, 0-1 (default 0.9)",
        ),
    ],
    exit_code_mappings=[
        ExitCodeMapping(exit_code=64, code="MALFORMED_INPUT", message="The capture could not be decoded."),
        ExitCodeMapping(exit_code=78, code="EXTRACTOR_CONTRACT", message="Invalid inputs, parameters or outputs."),
    ],
    output_format=FileOutputFormat.MANIFEST,
    default_timestamp_column="time_ns",
    default_timestamp_type="epoch_nanoseconds",
)
```

## Exit-code fallbacks

Exit-code mappings are the image's fallback errors, used when the container exits non-zero
without a valid termination-log document: a crash before reporting, or a runtime that cannot
write it. Register one per exit status the code uses, with a non-reserved code, a static
message and a retry decision matching the [failure policy](modeling.md#outputs-and-failure-policy).
A valid termination-log document always wins. Mappings live on the image, so changing them
means registering a new image; inspect the live ones with `image.exit_code_mappings`.

## Identity, discovery and provenance

For a new stable identity, `client.create_containerized_extractor(name, description=...,
labels=[...], properties={...})` returns the extractor. Labels and properties organize and
find extractors, such as by owning team or source format; they are not telemetry tags or image
provenance. `extractor.update(labels=..., properties=...)` replaces rather than appends, so
merge existing values first. Retrieve existing extractors with `get_containerized_extractor(rid)`
or `search_containerized_extractors(labels=..., properties=..., file_extension="bin")`, where
`file_extension` matches the active image's input suffixes. Preserve the RID in the project's
existing deployment convention.

Keep provenance in usual build output or existing release notes: source revision, build ID
and archive checksum, registered contract, version and returned image RID. An archive checksum
identifies those archive bytes; it is not an OCI image digest. Do not create a separate
state/config registry.

If registration raises `NominalAlreadyExistsError`, query
`extractor.search_container_images(tag=version)` and inspect the existing image's contract.
Reuse it only when release evidence establishes the same artifact and contract; a matching
source revision or version string is insufficient. Otherwise choose a deliberate new release
identity. Do not delete/recreate the old version or blindly retry with random suffixes.
