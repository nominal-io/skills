# Format inspection

Classify one file per intended ingest command:

| Files | Ingest form | Inspection / requirements |
| --- | --- | --- |
| `*.csv` | `ingest csv` | Read the first five rows; choose timestamps. |
| single `*.parquet` | `ingest parquet` | Inspect schema; choose timestamps. |
| parquet archive (`.tar`, `.tar.gz`, `.zip`) | `ingest parquet --archive` | Inspect its source schema when possible. |
| `*.mcap` | `ingest mcap`, plus 0..N `ingest mcap-video` | Inspect topics and schemas. |
| `*.jsonl`, `*.jsonl.gz` | `ingest journal-json` | Native timestamps. |
| ArduPilot `.bin` | `ingest ardupilot-dataflash` | Native timestamps. |
| `*.mp4`, `*.mkv`, `*.avi`, `*.ts`, `*.mov` | `ingest video` | Every file needs a start time. |

For CSV use `head -n 5 <FILE>`. For Parquet, use `duckdb -c "DESCRIBE SELECT * FROM '<FILE>' LIMIT 0"` or `parquet-tools schema <FILE>` when available. Timestamp rules are in [timestamp-detection.md](timestamp-detection.md).

Record the detected schema and timestamp evidence in the plan. Two files share a dataset only when their producing source, schema, and timestamp encoding match. If either schema or timestamp encoding differs, split the bucket and ask before treating it as one source.

## MCAP

An MCAP makes one timeseries dataset plus zero or more videos. Inspect topics with `mcap info <FILE>` when available; otherwise ask the user for each topic's schema.

- A topic is video only when its schema is exactly `foxglove.CompressedVideo` or it is confirmed raw H.264. Topic names alone are insufficient.
- Protobuf and ROS topics are timeseries.
- Unsupported schemas are skipped; use `--ignore-invalid-topics` when the parser should continue.
- Exclude every confirmed video topic from `ingest mcap`; plan a distinct `ingest mcap-video --topic <TOPIC>` for each video topic.

Show video, timeseries, and skipped topic groups in the plan. Derive MCAP video names/scopes from the topic after stripping its leading slash, for example `front_camera__camera_front`.

### MCAP decision procedure

1. Inspect the topic names and schema names with `mcap info <FILE>`.
2. Mark only an exact `foxglove.CompressedVideo` schema or a confirmed raw H.264 stream as video. Topic names such as `camera` or `image` are not enough.
3. Put protobuf and ROS topics in the timeseries dataset. Mark unsupported schemas as skipped.
4. Exclude every confirmed video topic from `nomctl ingest mcap`, then create one `nomctl ingest mcap-video --topic <TOPIC>` bucket for each video topic.
5. Use `--ignore-invalid-topics` only when the plan explicitly records which unsupported topics it allows the parser to skip.

MCAP timestamps are native. Do not pass tabular `--timestamp-column` or `--timestamp-type` flags to MCAP or MCAP-video commands.

Standalone video needs a start time for every file. Derive it from sidecar metadata first, then folder/date evidence, then file metadata. Record the source and ask when it is uncertain.

## Missing tools

For `mcap`, `duckdb`, `ffprobe`, or a parser for an xlsx sidecar: first check available installers (`which pipx uvx brew`). Ask the user before installing anything, showing the exact command and why it is needed. If they decline, ask them for the metadata instead of guessing.

Do not install an inspection tool as part of executing an approved ingest plan. Pause at the inspection step, get explicit approval for the exact installer command, then resume planning with the resulting evidence.
