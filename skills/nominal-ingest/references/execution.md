# Execution

Use `NOMINAL_PROFILE=<PROFILE>` on every command. Generate one `ingest_session_id` and apply `ingested-by-skill` plus the approved metadata on every created resource.

## Resource order

1. Create each new asset and capture its RID.
2. Create each historical run with both `--start` and `--end`; add asset RIDs with repeatable `--asset`.
3. For each dataset or video bucket, create/resolve the data source from its first file, attach it once to its owner, then append later files.

```sh
nomctl asset create --name <NAME> --label ingested-by-skill --property ingest_session_id <UUID> ...
nomctl run create --name <NAME> --start <RFC3339> --end <RFC3339> --asset <ASSET_RID> ...
```

Attach to an asset when the run has one, otherwise attach to the run:

```sh
nomctl asset add-dataset <ASSET_RID> <SCOPE> <DATASET_RID>
nomctl asset add-video   <ASSET_RID> <SCOPE> <VIDEO_RID>
nomctl run add-dataset   <RUN_RID>   <SCOPE> <DATASET_RID>
nomctl run add-video     <RUN_RID>   <SCOPE> <VIDEO_RID>
```

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

## Tight execution

Complete one bucket end-to-end (create, attach, append) before processing other independent buckets. Keep files inside a bucket serial. Once that template is proven, process independent buckets with at most roughly 5–10 concurrent ingests. Stop after a failed command or one of the first two failed attachments; read actual output before retrying.

## Verify and recover

Run `nomctl run get <RID>` for every run, then `nomctl channel list <DATASET_RID>` for each dataset. Add channel descriptions/units only from user-supplied metadata:

```sh
nomctl channel set <DATA_SOURCE_RID> <CHANNEL> --description <TEXT> --unit <UNIT>
```

There is no transaction. If an ingest fails partway through, do not auto-rollback; report every created RID and stop. Use `nomctl <subcommand> --help` when flags are uncertain or differ from this reference.
