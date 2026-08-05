# Execution

Use `NOMINAL_PROFILE=<PROFILE>` on every command. Generate one `ingest_session_id` and apply `ingested-by-skill` plus the approved metadata on every created resource.

The approved plan is the only write scope. Before every create or ingest command, confirm that its resource, owner, metadata, and file bucket appear in that plan.

## Resource order

1. Create each new asset and capture its RID.
2. Create each historical run with both `--start` and `--end`; add asset RIDs with repeatable `--asset`.
3. For each dataset or video bucket, create/resolve the data source from its first file, attach it once to its owner, then append later files.

```sh
nomctl asset create --name <NAME> --label ingested-by-skill --property ingest_session_id <UUID> ...
nomctl run create --name <NAME> --start <RFC3339> --end <RFC3339> --asset <ASSET_RID> ...
```

Create only resources approved in the plan. Resolve an approved reuse candidate with `get` before writing. A run may link to multiple assets with repeated `--asset`, but do not guess which asset produced an ambiguous source.

Use the generated `ingest_session_id` and approved labels/properties consistently on each newly created resource. Do not add run-specific metadata to a durable asset, and do not overwrite existing labels/properties while reusing a resource.

## First file, attach, then append

For every dataset bucket, complete the first file before starting an append:

```sh
# First CSV file creates the dataset and receives creation metadata.
nomctl ingest csv <FILE_1> --name <DATASET_NAME> \
  --timestamp-column <COLUMN> --timestamp-type <TYPE> \
  --label ingested-by-skill

# Attach once, after the dataset RID is captured.
nomctl asset add-dataset <ASSET_RID> <SCOPE> <DATASET_RID>

# Every later compatible file appends without metadata or reattachment.
nomctl ingest csv <FILE_2> --dataset <DATASET_RID> \
  --timestamp-column <COLUMN> --timestamp-type <TYPE>
```

For MCAP, exclude confirmed video topics on both the first file and appends. For Parquet, keep the same timestamp choice across all files in the bucket. For a relative timestamp, preserve the same offset for the complete bucket.

Videos use the same lifecycle with a typed video RID:

```sh
nomctl ingest video <FILE_1> --name <VIDEO_NAME> --start <RFC3339>
nomctl asset add-video <ASSET_RID> <SCOPE> <VIDEO_RID>
nomctl ingest video <FILE_2> --video <VIDEO_RID> --start <RFC3339>
```

Use stable snake_case scope names such as `dataflash`, `mcu_telemetry`, or `front_camera`. A scope identifies the source across runs, so do not derive it from an individual filename or flight. For MCAP video, derive it from the confirmed topic after stripping the leading slash.

## Failure boundaries

An ingest is not transactional. If the first bucket fails, stop before starting another bucket. If an attachment fails, stop after the first or second failure and inspect the exact command output instead of retrying the template across more sources.

Never auto-rollback an ingest. Report created resources and RIDs so the user can decide whether to remove, reuse, or append to them. Do not silently create a second asset, run, dataset, or video after an uncertain failure.

The following conditions require a user decision before continuing:

- A reused asset has a matching scope but the existing data source is not confirmed compatible.
- Two candidate files have different schema or timestamp encodings.
- A run has multiple assets and the data-source owner is unclear.
- A required timestamp, video start time, or historical run end cannot be derived with confidence.
- The installed CLI rejects a documented flag and `nomctl <subcommand> --help` does not establish a safe replacement.

## Optional channel polish

Only after ingestion and attachment succeed, use channel metadata supplied by the user or sidecars. Do not invent descriptions, units, or engineering conversions from a column name:

```sh
nomctl channel list <DATASET_RID>
nomctl channel set <DATASET_RID> <CHANNEL> --description <TEXT> --unit <UNIT>
```

## Read, reuse, and report

Use targeted reads before writes. Prefer search when a name, identifier, label, or property narrows the candidate set; do not dump an entire non-trivial workspace just to find one resource.

```sh
nomctl asset search --substring <TEXT>
nomctl run search --substring <TEXT>
nomctl asset get <ASSET_RID>
nomctl run get <RUN_RID>
nomctl dataset get <DATASET_RID>
```

For a reused asset, inspect its attached data sources before creating a new dataset or video. Reuse an existing data source only when its stable scope, schema, and timestamp encoding are compatible with the approved bucket. Otherwise create a distinct scope and say why in the plan.

Resource updates are not a shortcut around the plan. Read the current labels and properties before an approved update, merge deliberately, and never clear or replace user metadata to make an ingest fit a naming convention.

After all approved buckets finish, verify the model from the owners that users will open:

```sh
nomctl run get <RUN_RID>
nomctl channel list <DATASET_RID>
```

Check that every run exposes its intended data sources through the correct asset or run owner. Spot-check channel names after tabular ingest. The final report includes the following for every approved bucket:

- Whether its owner was created or reused.
- The resource name, RID, and available Nominal web URL.
- The stable scope used for the attachment.
- Every ingested file and whether it created or appended.
- The timestamp or video-start evidence used.
- Any skipped file, unsupported MCAP topic, or partial failure.

## Known failure modes

Treat a timestamp unit mismatch as a blocking problem. For example, importing epoch milliseconds as epoch seconds produces data in 1970. If timestamp confidence is below high, show the uncertainty in the plan and get confirmation before writes.

Re-running a folder without checking for existing assets, runs, datasets, and videos creates duplicates. Search and offer reuse before creating a resource with a meaningful matching name, identifier, label, or property.

Do not use raw `nomctl api`, `nomctl endpoint list`, or other endpoint escape hatches. Dedicated subcommands constrain the operation to the approved ingest workflow; raw endpoints can archive or delete data, alter configuration, or cross tenant boundaries.

## Approved resource mutations

Use explicit dedicated subcommands when the approved plan requires a resource change beyond ingest. Empty datasets and videos are exceptional: create them only when the plan establishes why ingest cannot create the source atomically.

```sh
nomctl asset create --name <NAME> --label <LABEL> --property <KEY> <VALUE>
nomctl run create --name <NAME> --start <RFC3339> --end <RFC3339> --asset <ASSET_RID>
nomctl dataset create --name <NAME>
nomctl video create --name <NAME>

nomctl asset update <ASSET_RID> --label <LABEL> --property <KEY> <VALUE>
nomctl run update <RUN_RID> --label <LABEL> --property <KEY> <VALUE>
nomctl dataset update <DATASET_RID> --label <LABEL> --property <KEY> <VALUE>
```

Creation and update are separate decisions. An approved ingest normally creates assets and runs only when no confirmed match exists. Updating an existing resource needs its own plan entry, a read of current metadata, and an explicit preservation strategy.

When a run has multiple assets, attach a source to the specific asset that produced it. A genuinely shared dataset can attach to the run only after the user confirms that exception. Never attach the same source to both a run and an asset merely to make it easier to find.

Attach to an asset when the run has one, otherwise attach to the run:

```sh
nomctl asset add-dataset <ASSET_RID> <SCOPE> <DATASET_RID>
nomctl asset add-video   <ASSET_RID> <SCOPE> <VIDEO_RID>
nomctl run add-dataset   <RUN_RID>   <SCOPE> <DATASET_RID>
nomctl run add-video     <RUN_RID>   <SCOPE> <VIDEO_RID>
```

Do not mix ownership for a run. If a run has assets, attach a source to the asset that produced it and let the run inherit it. Attach directly to the run only when no asset owns that source. When a source cannot be assigned to one asset, stop for a user decision.

## First file vs. append

The first file uses `--name` and receives creation metadata; later compatible files use the returned RID and never reattach. Do not combine metadata flags with an append.

```sh
# CSV / Parquet
nomctl ingest csv <FILE_1> --name <NAME> --timestamp-column <COL> --timestamp-type <TYPE> [--timestamp-offset <RFC3339>]
nomctl ingest csv <FILE_2> --dataset <DATASET_RID> --timestamp-column <COL> --timestamp-type <TYPE> [--timestamp-offset <RFC3339>]
nomctl ingest parquet <FILE> {--name <NAME> | --dataset <DATASET_RID>} --timestamp-column <COL> --timestamp-type <TYPE> [--archive]

# Native-timestamp data
nomctl ingest mcap <FILE> {--name <NAME> | --dataset <DATASET_RID>} --exclude-topic <VIDEO_TOPIC>... [--include-topic <TOPIC>]... [--ignore-invalid-topics]
nomctl ingest journal-json <FILE> {--name <NAME> | --dataset <DATASET_RID>} [--channel <NAME>]
nomctl ingest ardupilot-dataflash <FILE> {--name <NAME> | --dataset <DATASET_RID>}

# Video
nomctl ingest video <FILE> {--name <NAME> | --video <VIDEO_RID>} --start <RFC3339>
nomctl ingest mcap-video <FILE> --topic <TOPIC> {--name <NAME> | --video <VIDEO_RID>}
```

Capture typed RIDs from output before using them. For example: `Dataset RID: ri.…` and `Video RID: ri.…`. If a capture is empty, fix it before the next write.

The CLI emits typed RID lines rather than a generic `RID:`. Capture the exact resource type and verify it is non-empty before reusing it:

```sh
nomctl ingest csv <FILE> --name <NAME> ... | tee /tmp/ingest.out
DATASET_RID=$(grep -oE 'Dataset RID: ri\\.[^ ]+' /tmp/ingest.out | awk '{print $3}')

nomctl ingest video <FILE> --name <NAME> ... | tee /tmp/ingest.out
VIDEO_RID=$(grep -oE 'Video RID: ri\\.[^ ]+' /tmp/ingest.out | awk '{print $3}')
```

An empty RID must stop the ingest. Reusing it produces invalid-RID failures on every later attachment or append and leaves a partial workspace behind.

## Tight execution

Complete one bucket end-to-end (create, attach, append) before processing other independent buckets. Keep files inside a bucket serial. Once that template is proven, process independent buckets with at most roughly 5–10 concurrent ingests. Stop after a failed command or one of the first two failed attachments; read actual output before retrying.

Within a bucket, the first file must finish before later files can use its dataset or video RID. Across proven independent buckets, bounded concurrency reduces upload time without making a bad command template fan out across the workspace. There is no batch transaction: every `nomctl ingest` is independent and a halfway failure can leave resources behind.

## Command guardrails

Use `nomctl <subcommand> --help` when a flag in this reference does not match the installed CLI. Do not invent a flag or retry a failed command across multiple files.

All ingestion forms create with `--name` or append with an existing RID. Creation metadata belongs only on the first file; do not combine metadata flags with an append:

```sh
nomctl ingest csv <FILE> {--name <NAME> | --dataset <RID>} --timestamp-column <COLUMN> --timestamp-type <TYPE>
nomctl ingest parquet <FILE> {--name <NAME> | --dataset <RID>} --timestamp-column <COLUMN> --timestamp-type <TYPE>
nomctl ingest mcap <FILE> {--name <NAME> | --dataset <RID>} --exclude-topic <VIDEO_TOPIC>...
nomctl ingest journal-json <FILE> {--name <NAME> | --dataset <RID>}
nomctl ingest ardupilot-dataflash <FILE> {--name <NAME> | --dataset <RID>}
nomctl ingest video <FILE> {--name <NAME> | --video <RID>} --start <RFC3339>
nomctl ingest mcap-video <FILE> --topic <TOPIC> {--name <NAME> | --video <RID>}
```

Use `--timestamp-offset <RFC3339>` with a relative tabular timestamp. MCAP and MCAP-video use native timestamps and never take tabular timestamp flags.

## Verify and recover

Run `nomctl run get <RID>` for every run, then `nomctl channel list <DATASET_RID>` for each dataset. Add channel descriptions/units only from user-supplied metadata:

```sh
nomctl channel set <DATA_SOURCE_RID> <CHANNEL> --description <TEXT> --unit <UNIT>
```

There is no transaction. If an ingest fails partway through, do not auto-rollback; report every created RID and stop. Use `nomctl <subcommand> --help` when flags are uncertain or differ from this reference.

The completion report names every created and reused asset, run, dataset, and video; includes each RID and available web URL; records source attachments; and identifies the first partial failure. It must let the user find or clean up every affected resource without reconstructing the run.
