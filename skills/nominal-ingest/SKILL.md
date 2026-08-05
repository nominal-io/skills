---
name: nominal-ingest
description: Nominal ingest for a folder of test or campaign data. Use when a user wants CSV, Parquet, MCAP, journald, ArduPilot, or video files imported from disk.
---

# Nominal ingest

Turn an on-disk collection into a clean Nominal model: durable assets, bounded historical runs, and reusable data sources. Work in two gates: **plan** the entire ingest, then **execute** only after the user explicitly approves that plan.

Use only dedicated `nomctl` subcommands. When the needed operation has no dedicated subcommand, ask the user to perform it; raw API and endpoint commands are outside this skill.

## 1. Establish a safe starting point

Read [references/data-model.md](references/data-model.md) before deciding what to create. Read [references/metadata-conventions.md](references/metadata-conventions.md) before proposing labels or properties.

Verify a profile before inspecting or changing Nominal:

```sh
nomctl config profile list
nomctl --profile <PROFILE> user who-am-i
```

Use `NOMINAL_PROFILE=<PROFILE> nomctl <SUBCOMMAND> ...` on every later command. Each shell is fresh, so an earlier `export` does not persist. If no usable profile exists, follow [references/authentication.md](references/authentication.md); the user enters their own token in their terminal.

Completion criterion: identify a working profile and its workspace, or stop for the user to configure one.

## 2. Inventory the folder

Read [references/folder-patterns.md](references/folder-patterns.md). Walk the tree to depth 3 by default, identify candidate run and asset axes, and read every plausible sidecar (`metadata.*`, `manifest.*`, `README*`, `NOTES*`, small logs, Markdown, and text). Sidecar prose overrides filename and tree inference.

Classify every ingestible file and record its owner candidate, source candidate, and time evidence. Ignore hidden files, lock files, `.DS_Store`, and obvious build artifacts. Ask before descending further or scanning a tree with tens of thousands of files.

Read [references/format-inspection.md](references/format-inspection.md) for supported formats, required inspection, MCAP topic routing, and unavailable-tool handling. For CSV and Parquet, also read [references/timestamp-detection.md](references/timestamp-detection.md).

Completion criterion: every file to be ingested has a format, a proposed owner/source, and sufficient timestamp evidence or an explicit question for the user.

## 3. Choose the model and buckets

Use the folder patterns and data model to propose the smallest durable model:

- Default a small one-off dump to one run and no asset.
- Create an asset only with positive evidence of a stable, identifiable thing; reuse a confirmed match where possible.
- For historical data, every run has both `start` and `end`.
- A dataset is a **table**, not a file: bucket files by `(owner, source)` only when their schema and timestamp encoding match. One video is likewise `(owner, camera/topic)`.
- Attach data to the asset when the run has one; attach directly to a run only when it has no asset. A multi-asset ambiguity needs a user decision.

Search before creating when you have a meaningful name, identifier, label, or property hint. Use `asset get` to find existing data sources on a reused asset; do not create a parallel dataset or video when the matching stable scope already exists.

For detailed modeling decisions, including two-level trees, re-ingest, source bucketing, timestamps, and metadata, read [references/data-model.md](references/data-model.md), [references/folder-patterns.md](references/folder-patterns.md), [references/timestamp-detection.md](references/timestamp-detection.md), and [references/metadata-conventions.md](references/metadata-conventions.md) as applicable.

Completion criterion: every proposed resource has an owner, a stable name/scope, files in ingest order, and a documented start/end source; every uncertainty is ready for the plan.

## 4. Show one complete plan

Generate one `ingest_session_id` UUID. Read and fill out [references/plan-template.md](references/plan-template.md), including all assets, runs, dataset/video buckets, file order, timestamp choices, metadata, existing-resource reuse, MCAP topic classification, and unresolved questions.

Wait for an explicit **go**. If the user revises anything, show the complete revised plan and wait again. Do not create or ingest a subset before approval.

Completion criterion: the user has explicitly approved the exact plan to execute.

## 5. Execute in a tight loop

Read [references/execution.md](references/execution.md) before the first write. It is the command source for resource creation, each ingest format, attachment, RID capture, concurrency, verification, and failure handling.

In order: create or resolve assets; create or resolve runs; validate one complete dataset/video bucket end-to-end; then process the remaining independent buckets with bounded parallelism. Within a bucket, the first file creates or resolves the resource and every later file appends to its RID. Attach each data source once to its owner.

Do not improvise CLI flags. Run `nomctl <subcommand> --help` when the reference and installed CLI disagree. On a failed command, inspect its output and stop before repeating that template across more files. Do not auto-rollback a partial ingest.

Completion criterion: every approved file succeeded or the first failure is reported with the resources already created.

## 6. Verify and report

For every run, use `nomctl run get <RID>` and confirm its intended data sources are visible through the correct owner. List dataset channels and spot-check their names. When sidecars supply a channel dictionary, optionally add channel descriptions and units.

Report created and reused resource names, RIDs, web URLs, source attachments, and any partial failures. The report must let the user find or clean up every resource without reconstructing the run.

## Outside this skill

Streaming/live connections are not folder ingest. Direct users to the streaming documentation. For data already modeled in Nominal, plan an append to the confirmed dataset or video RID rather than repeating asset/run creation.
