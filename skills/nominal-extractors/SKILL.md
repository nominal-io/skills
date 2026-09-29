---
name: nominal-extractors
description: Use when building, testing, registering, or debugging Nominal containerized extractors — Docker images, written in any language, that convert proprietary or unsupported files during ingest. Covers the container contract (environment variables, mounted inputs, manifest.json, structured errors in the termination log, exit codes), the Python extractor framework (nominal.experimental.extractor decorators), image registration (register_image, registration_kwargs, nom container), and containerized ingest failures. For ordinary ingestion of formats Nominal already parses, use nominal-ingest instead.
---

# Nominal containerized extractors

A containerized extractor is a Docker image Nominal runs during ingest: uploaded files are
mounted as inputs, your parser writes outputs, and Nominal ingests the declared files into a
dataset. Use one for recurring proprietary or unsupported formats, including uploads from the
web app. For supported formats or a one-off local conversion, use ordinary ingestion. They may
also be used for doing any consistent post-processing or timestamp alignment that may be
required for file formats that are supported natively (e.g., post processing the `timestamp`
column in otherwise valid `.parquet` files).

The **ContainerizedExtractor** is the stable identity uploaders select; its versioned
**ContainerImages** carry the execution contract (inputs, parameters, output format, timestamp
defaults, exit-code mappings). Registration and activation are separate. The active image runs
future jobs. Output measurements become **channels**, timestamps place samples on a
**timeline**, and supported **tags** distinguish series within the **dataset**.

## How a run works

The platform talks to the container only through the environment and the filesystem, so any
language that runs in a `linux/amd64` image can implement an extractor:

1. An uploader submits files, parameter values and tags, through the web app or the SDK's
   `add_containerized`.
2. Nominal resolves job-level timestamp metadata (the request's override, else the image
   default), mounts each file under `/input`, and runs the active image as a non-root user with
   each input's path and each parameter's value in its registered environment variable and the
   output directory in `$OUTPUT_DIR`.
3. The container parses, writes outputs under `$OUTPUT_DIR` plus a `manifest.json` describing
   each one, and exits.
4. Exit 0: Nominal uploads and ingests the declared files. Non-zero: the job fails with the
   structured error the container wrote to the termination log (`/dev/termination-log`), else
   the image's exit-code mapping for that exit status.

[Contract](references/contract.md) is the authoritative wire-level description. Explain it in
these terms when someone is new to extractors, before any SDK detail. Choose the
implementation path by the parser, not the SDK:

| Path | Use when | Consequence |
|---|---|---|
| Python framework (`nominal.experimental.extractor`, `nominal>=1.171`) | The parser is or can be Python | Decorators bind inputs and parameters, write `manifest.json`, report structured errors, and export registration metadata from one declaration. |
| Direct contract implementation | Another language, or wrapping an existing binary | The code reads the environment and writes `manifest.json` and any structured error itself; registration metadata is kept in a checked-in `nom` config or script and tested against the code. |

Everything else runs outside the container, whatever language the extractor uses:
registration with the `nom` CLI or the Python SDK, scripted ingest with the Python SDK, and
no-code uploads through the web app.

## Guide the next decision

Inspect existing parser/registration code and the project README first. Derive file facts
from samples or a format specification; reuse settled preferences from the conversation and
project, including the implementation language. Separate observed facts, agreed choices, and
unresolved assumptions. Recommend a choice with its consequence, then ask only the next
question blocking progress. Do not repeat settled questions or turn every modeling detail into
an intake questionnaire.

Keep executable choices and defaults in parser/registration code, with concise rationale in
the project README (create one for a new project). Read live deployed state from Nominal when
available; local code expresses intent, not proof of deployment. Do not add a parallel JSON
state/config file or a new decision document. [Modeling](references/modeling.md) covers what
to settle and an illustrative README note.

## Work from the relevant stage

New work follows these stages; debugging or existing work resumes where the evidence points.
Read the linked reference before changing that stage. Progress when its evidence is adequate
and the action is authorized; an already agreed contract needs no repeated approval.

| Stage | Input | Output and evidence to progress |
|---|---|---|
| Understand the files | Samples/spec, existing code and README, intended comparisons | Observed structure, measurements, units, clocks, dimensions; name missing evidence instead of guessing. |
| Agree on the contract | Observations and existing preferences | Implementation path, inputs/parameters, output mode, timestamps, tags, units, and failure codes with rationale; resolve consequential unknowns using [modeling](references/modeling.md). |
| Author and validate locally | Contract and representative fixtures | Parser and focused checks of decoded values/time, declared outputs, error codes and edge cases; report actual results using [authoring](references/authoring.md) and [contract](references/contract.md). |
| Build and register | Validated parser, Docker, configured Nominal access | Settled base image, image archive with verified architecture, a passing local conformance run, registration script or config, and observed registration result; use [registration](references/registration.md). |
| Activate and operate | Registered image, authorization and representative upload | Observed active image, terminal extraction job and completed dataset-file ingestion, then inspect resulting data; use [running](references/running.md). |

Check only capabilities needed for the current stage. Inspect mentioned paths/profiles before
asking for missing inputs, and reuse configured authentication rather than requesting tokens
in chat. With the parser's toolchain but no Docker, validate locally and hand off build
commands. With Docker but no Nominal access, build, run the conformance check, and hand off a
registration script or config and exact commands. With none of these, author/review what the
supplied evidence supports. Keep project outputs in the project, and distinguish executed
checks from instructions still awaiting execution; generated commands do not prove build,
registration, activation, or successful ingest.

## Keep the execution contract aligned

- Write outputs under `$OUTPUT_DIR`, declare every intended output, and write `manifest.json`
  last; the Python runtime writes it for you and owns the name.
- Register the output format the code implements, `MANIFEST` for new work.
  `registration_kwargs()` sets it for `@manifest_extractor`; explicit `register_image` calls
  and the CLI otherwise default to `PARQUET`.
- Keep environment-variable names identical across code, registration, and callers'
  `sources`/`arguments`; registration never infers them from code in other languages.
- Report expected failures as structured errors in the termination log, with stable,
  non-reserved error codes and distinct exit statuses, and register an exit-code mapping for
  each status where the registration path supports it. Never log the container environment; it
  can carry credentials.
- Build for `linux/amd64` and confirm with
  `docker image inspect <tag> --format '{{.Os}}/{{.Architecture}}'` before registration;
  a READY image does not prove it can run.
- Registration does not activate an image. Verify the active image after activation.
- Confirm channel prefixes, units and videos on the target deployment after a representative
  ingest; some ingest routes ignore those manifest options.
- Wait out both stages of an ingest — the container, then its files — with
  `job.as_files_ingested(timeout=...)`, and check each file's status; see
  [running](references/running.md).

## Locate bundled resources

`references/...` paths are relative to the installed directory containing this `SKILL.md`,
not the project or current working directory. Resolve that location through the host's skill
path/resource interface, and read them through the host interface when the resources have no
filesystem paths. This skill bundles no executables: the checks it asks for are ordinary
`docker`, `nom`, Python SDK and project-toolchain commands, so a project or CI pipeline runs
them directly rather than depending on an agent's plugin cache.
