---
name: nominal-extractors
description: Use when building, testing, registering, or debugging Nominal containerized extractors for reusable server-side file conversion, extractor manifests, image registration (register_image, nom container), or containerized ingest failures. For ordinary ingestion of formats Nominal already parses, use nominal-ingest instead.
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
defaults). Registration and activation are separate. The active image runs future jobs.
Inside the container use `nominal.experimental.extractor`; outside use `NominalClient` or
`nom container`. Output measurements become **channels**, timestamps place samples on a
**timeline**, and supported **tags** distinguish series within the **dataset**.

## Guide the next decision

Inspect existing parser/registration code and the project README first. Derive file facts
from samples or a format specification; reuse settled preferences from the conversation and
project. Separate observed facts, agreed choices, and unresolved assumptions. Recommend a
choice with its consequence, then ask only the next question blocking progress. Do not repeat
settled questions or turn every modeling detail into an intake questionnaire.

Keep executable choices and defaults in parser/registration code, with concise rationale in
the existing project README. Read live deployed state from Nominal when available; local
code expresses intent, not proof of deployment. Do not add a parallel JSON state/config file
or a new decision document. [Modeling](references/modeling.md) covers what to settle and an
illustrative README note.

## Work from the relevant stage

New work follows these stages; debugging or existing work resumes where the evidence points.
Read the linked reference before changing that stage. Progress when its evidence is adequate
and the action is authorized; an already agreed contract needs no repeated approval.

| Stage | Input | Output and evidence to progress |
|---|---|---|
| Understand the files | Samples/spec, existing code and README, intended comparisons | Observed structure, measurements, units, clocks, dimensions; name missing evidence instead of guessing. |
| Agree on the contract | Observations and existing preferences | Inputs/parameters, output mode, timestamps, tags, and failure policy with rationale; resolve consequential unknowns using [modeling](references/modeling.md). |
| Author and validate locally | Contract and representative fixtures | Parser and focused checks of decoded values/time, declarations and edge cases; report actual results using [authoring](references/authoring.md). |
| Build and register | Validated parser, Docker, configured Nominal access | Settled base image, image archive with verified architecture, registration script, and observed registration result; use [registration](references/registration.md). |
| Activate and operate | Registered image, authorization and representative upload | Observed active image, terminal extraction job and completed dataset-file ingestion, then inspect resulting data; use [running](references/running.md). |

Check only capabilities needed for the current stage. Inspect mentioned paths/profiles before
asking for missing inputs, and reuse configured authentication rather than requesting tokens
in chat. With Python but no Docker, validate locally and hand off build commands. With Docker
but no Nominal access, build/inspect and hand off a registration script and exact commands.
With neither, author/review what the supplied evidence supports. Keep project outputs in the
project, and distinguish executed checks from instructions still awaiting execution; generated
commands do not prove build, registration, activation, or successful ingest.

## Keep the execution contract aligned

- Write outputs under `ctx.output_dir` and declare every intended output; the runtime owns
  `manifest.json`.
- Match the decorator to the registered output format; explicitly register `MANIFEST` for
  new manifest extractors (registration otherwise defaults to `PARQUET`).
- Build for `linux/amd64` and confirm with
  `docker image inspect <tag> --format '{{.Os}}/{{.Architecture}}'` before registration;
  a READY image does not prove it can run.
- Registration does not activate an image. Verify the active image after activation.
- Wait for the extraction job to finish before enumerating its dataset files, then wait for
  those files to ingest; see [running](references/running.md).

## Locate bundled resources

`references/...` paths are relative to the installed directory containing this `SKILL.md`,
not the project or current working directory. Resolve that location through the host's skill
path/resource interface, and read them through the host interface when the resources have no
filesystem paths. This skill bundles no executables: the checks it asks for are ordinary
`docker`, `nom` and Python SDK commands, so a project or CI pipeline runs them directly
rather than depending on an agent's plugin cache.
