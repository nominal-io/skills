# The container contract

This page is the wire-level contract between Nominal and an extractor image, independent of
language. The Python runtime (`nominal.experimental.extractor`) is one implementation of it;
a Go, Rust, C++, Java or shell entrypoint that does the same things is equally valid. Use this
page to implement the contract directly, to explain it to someone, or to debug either path.

A run is a batch job: Nominal mounts the uploaded files, sets environment variables, runs the
image's entrypoint, and after it exits uploads and ingests the outputs it declared. Nothing is
passed on the command line, and the container never calls back to Nominal. The entrypoint
normally runs once; after a failure the platform may start one more attempt with fresh
volumes, so never depend on state left by an earlier attempt.

## Runtime environment

| Aspect | Contract |
|---|---|
| Architecture | `linux/amd64`. Other architectures register and activate, then fail with an exec format error. |
| User | A fixed non-root UID chosen by the platform, not the image's `USER`, with capabilities dropped. Nothing may need root, and files the image ships must be readable (binaries executable) by an arbitrary UID. |
| `$HOME` | `/home`, a writable mount that starts empty on every attempt and hides everything the image placed under `/home`, including a base image's `/home/<user>`. Use it for scratch files; never install dependencies there. |
| `$OUTPUT_DIR` | A writable directory for outputs. In manifest mode only declared files are ingested; in single-file mode it must hold exactly the one output file and nothing else, not even a subdirectory. |
| Inputs | Each uploaded file is mounted under `/input`; its absolute path is the value of the input's registered environment variable. Read the path from that variable rather than constructing it. An optional input the request omitted leaves its variable unset. |
| Parameters | Each supplied value is the string value of the parameter's registered environment variable. An omitted optional parameter is unset; an empty string is a supplied value. |
| Logs | stdout and stderr land in a log dataset; only the first 1 MiB of each attempt is kept. |
| Resources | Memory is limited, and an out-of-memory kill reports `EXTRACTOR_OOM_KILLED`; stream large inputs instead of loading them whole. Run time is limited too, currently to about 50 minutes, and a run killed at the deadline reports `UNKNOWN` or the image's mapping for the kill's exit status. |
| Network | Do not depend on it. Deployments may be air-gapped; ship everything the parser needs in the image or as an input. |

### Metadata variables

Newer platforms also inject `_NOMINAL_*` variables. They are best-effort enrichment: tolerate
their absence (every local run) and unknown fields, and never require them for correctness.

| Variable | Value |
|---|---|
| `_NOMINAL_OUTPUT_FORMAT` | Registered output format name: `MANIFEST`, `PARQUET`, `CSV` or `AVRO_STREAM`. Useful as a startup check that code and registration agree. |
| `_NOMINAL_INPUTS` | JSON list of mounted inputs: `[{"name": "Raw file", "environmentVariable": "RAW_FILE", "path": "/input/capture.bin", "required": true}]`. Omitted optional inputs are not listed. |
| `_NOMINAL_PARAMETERS` | JSON list of registered parameters, without values: `[{"name": "Quality threshold", "environmentVariable": "THRESHOLD", "required": false}]`. |
| `_NOMINAL_INGEST_JOB_RID`, `_NOMINAL_DATASET_RID` | RIDs of this job and its target dataset, for log lines. |
| `_NOMINAL_ADDITIONAL_TAGS` | JSON object of the ingest request's tags, e.g. `{"stand": "Stand-A"}`. They are applied to all data anyway; read them only when the parser needs the value. |
| `_NOMINAL_TIMESTAMP_METADATA` | JSON of the job-level timestamp metadata outputs fall back to, e.g. `{"seriesName": "time_ns", "timestampType": {"type": "absolute", "absolute": {"type": "epochOfTimeUnit", "epochOfTimeUnit": {"timeUnit": "NANOSECONDS"}}}}`. |

The environment can also carry platform credentials. Never print, log or write out the whole
environment, and never echo `_NOMINAL_*` values wholesale into outputs or error messages.
`OUTPUT_DIR`, `HOME`, names beginning with `_NOMINAL_`, and `NOMINAL_EXTRACTOR_INPUT_DIR`
(used by the Python runtime) are reserved: do not register inputs or parameters under them.

## Exit status and structured errors

Exit `0` means success: the platform uploads and ingests the declared outputs. Any other
status fails the job. Before a non-zero exit, write one JSON object to `/dev/termination-log`:

```json
{"code": "MALFORMED_INPUT", "message": "Header checksum mismatch at byte 512", "retryable": false, "details": {"byte_offset": "512"}}
```

| Field | Rule |
|---|---|
| `code` | Required, non-blank. Use an identifier matching `[A-Z][A-Z0-9_]*`, stable across releases. Without a valid `code` the document is ignored. |
| `message` | Shown with the failure; a blank message becomes a generic one. Keep it free of secrets and bulk data. |
| `retryable` | Boolean, default `false`. `true` only when retrying the same input could succeed. |
| `details` | Optional flat object of string, number or boolean values; nested values are dropped. |

Write only the JSON document and keep it within 4,096 bytes (the Kubernetes termination
message limit), truncating the message rather than the JSON. The platform resolves a failed
container's error in this order:

1. a valid termination-log document;
2. the image's registered exit-code mapping for the exit status (see
   [registration](registration.md#exit-code-fallbacks)), which matters only when step 1 is
   missing: a crash before reporting, or a failed write;
3. a platform fallback: `EXTRACTOR_OOM_KILLED` for an out-of-memory kill, otherwise `UNKNOWN`
   with a generic message naming the exit status.

Also print the same JSON to stderr so it appears in the job log. Treat the termination log as
best-effort: if writing it fails, still print the error and exit with the mapped status, so the
registered fallback applies. Give each failure class
its own exit status from 1 through 255, avoiding 126, 127 and 128 or higher, which shells and
signals already use. One convention borrows `sysexits`: 64 for malformed input, 65 for input
that decodes but holds no usable data, 78 for configuration or contract errors. Unexpected
failures may exit 1 with a stack trace on stderr.

The platform owns `IMAGE_PULL_FAILED`, `EXTRACTOR_TIMEOUT`, `EXTRACTOR_UNSCHEDULABLE`,
`EXTRACTOR_OOM_KILLED`, `OUTPUT_UPLOAD_FAILED`, `INVALID_OUTPUT` and `UNKNOWN`; extractors
must not emit or register them. The Python SDK exposes the current set as
`nominal.core.container_image.RESERVED_EXTRACTOR_ERROR_CODES`. Not all are emitted today:
problems with `manifest.json` or the files it names currently surface as
`OUTPUT_UPLOAD_FAILED`, and a timeout as described under Resources.

## Output modes

The code must implement the output format the image is registered with. Both the SDK's
explicit `register_image` arguments and the CLI default to `PARQUET` when none is given.

| Registered format | Container writes | Per-output control |
|---|---|---|
| `MANIFEST` (recommended) | Any number of output files plus `$OUTPUT_DIR/manifest.json` describing each | Ingest type, timestamps, tag columns, channel prefix and units per file; videos |
| `PARQUET`, `CSV`, `AVRO_STREAM` (legacy) | Exactly one file of that format | None: the job-level timestamp metadata and request tags apply |

Keep single-file mode only for images already registered that way; changing an image's format
requires registering a new image. In manifest mode, write `manifest.json` last, after every
file it names is complete, and do not list `manifest.json` itself. A missing or unparseable
manifest, one with no outputs, or one naming a missing file or a path outside `$OUTPUT_DIR`
fails the job. The platform rejects some extension mismatches, such as a `TABULAR` entry that
is neither CSV nor Parquet, but not all: others fail or misparse later, so keep every
extension consistent with its `ingestType`.

## manifest.json

A JSON object with camelCase field names, following the Conjure wire format: absent optional
and map fields read as empty, and unions carry a `"type"` discriminator. Emitting every field
explicitly, as the Python runtime does, is the conservative choice; do not add other keys.

```json
{
  "outputs": [
    {
      "ingestType": "TABULAR",
      "relativePath": "telemetry/engine.csv",
      "tagColumns": {"motor": "motor_id"},
      "channelPrefix": "engine.",
      "timestampMetadata": {
        "seriesName": "elapsed_us",
        "epochTimeUnit": "MICROSECONDS",
        "relativeOffset": "2026-09-01T12:00:00.000000000Z"
      },
      "units": {"engine.pressure": "kPa"}
    },
    {
      "ingestType": "AVRO_STREAM",
      "relativePath": "bus.avro",
      "tagColumns": {},
      "channelPrefix": null,
      "timestampMetadata": {"seriesName": "timestamps", "epochTimeUnit": "NANOSECONDS", "relativeOffset": null},
      "units": {"voltage": "V"}
    },
    {
      "ingestType": "JSON_L",
      "relativePath": "events.jsonl",
      "tagColumns": {},
      "channelPrefix": null,
      "timestampMetadata": {"seriesName": "ts", "epochTimeUnit": "SECONDS", "relativeOffset": null},
      "units": {}
    }
  ],
  "videoOutputs": [
    {
      "relativePath": "front.mp4",
      "channel": "camera/front",
      "timestampManifest": {
        "type": "noManifest",
        "noManifest": {
          "startingTimestamp": {"seconds": 1788264000, "nanos": 0},
          "scaleParameter": {"type": "trueFrameRate", "trueFrameRate": 59.94}
        }
      }
    },
    {
      "relativePath": "rear.mp4",
      "channel": "camera/rear",
      "timestampManifest": {
        "type": "frameTimestampsRelativePath",
        "frameTimestampsRelativePath": "rear.mp4.timestamps.json"
      }
    }
  ]
}
```

### Output entries (`outputs`)

| Field | Rule |
|---|---|
| `ingestType` | `TABULAR` for `.csv`, `.csv.gz`, `.parquet` or `.parquet.gz`; `AVRO_STREAM` for `.avro` or `.avro.gz`; `JSON_L` for `.jsonl` or `.jsonl.gz`, ingested as logs. |
| `relativePath` | Path under `$OUTPUT_DIR` with forward slashes; subdirectories are allowed, absolute paths and `..` are not. The same file may appear in several entries, e.g. one table ingested under two timestamp columns. |
| `tagColumns` | `TABULAR` only: tag name to the column carrying its values. That column becomes the tag and is not also ingested as a channel. |
| `channelPrefix` | `TABULAR` and `AVRO_STREAM`: string prepended to every channel name from this file, or `null`. |
| `units` | Channel name to unit symbol. Keys are final channel names, after `channelPrefix` is applied; symbols pass through unchanged. Check the resulting channel units after a representative ingest; see [deployment differences](#deployment-differences). |
| `timestampMetadata` | `null` to inherit the job-level metadata, or a numeric description of this file's timestamps (below). |

`timestampMetadata` describes numeric timestamps only:

- `seriesName`: the timestamp column (`TABULAR`) or top-level field (`JSON_L`). For
  `AVRO_STREAM` it is always `timestamps`, the schema's field.
- `epochTimeUnit`: `SECONDS`, `MILLISECONDS`, `MICROSECONDS` or `NANOSECONDS`, matching the
  stored numbers. The wrong unit misplaces every sample by a factor of 1,000.
- `relativeOffset`: `null` for absolute Unix-epoch numbers, or an ISO 8601 UTC instant that the
  numbers count from. It applies to every ingest type that takes `timestampMetadata`. The Python
  runtime writes nine fractional digits, as in `2026-09-01T12:00:00.000000000Z`; matching that
  form is the safe choice.

String timestamps (ISO 8601 or a custom format) cannot be declared here. Omit the entry's
metadata so it inherits the job-level value, which supports every timestamp type.

### Video entries (`videoOutputs`)

`channel` names the dataset channel the video lands on; the file must be `.avi`, `.m2ts`,
`.mkv`, `.mp4` or `.ts`. `timestampManifest` is exactly one of:

- `noManifest`: frame times come from the video's own presentation timestamps, offset from
  `startingTimestamp` (`{"seconds", "nanos"}` since the Unix epoch). Optional `scaleParameter`
  corrects a playback-rate mismatch with one of `{"type": "trueFrameRate", "trueFrameRate": f}`,
  `{"type": "scaleFactor", "scaleFactor": f}` or
  `{"type": "endingTimestamp", "endingTimestamp": {"seconds", "nanos"}}`.
- `frameTimestampsRelativePath`: path under `$OUTPUT_DIR` to a JSON sidecar holding an array of
  integer Unix-epoch nanoseconds, one per frame, e.g. `[1788264000000000000, 1788264000033366700]`.
  The sidecar needs no entry of its own.

### Deployment differences

Some manifest options take effect only on Nominal's newer ingest route, and a deployment still
on the earlier route ignores them silently: `channelPrefix` and `units` are dropped, Avro
`timestampMetadata` is ignored in favor of the default reading (epoch nanoseconds, as for
`Dataset.add_avro_stream`), and `videoOutputs` are skipped, so a manifest with only videos
fails. On either route, video also needs video ingest enabled on the deployment, or any video
entry fails the manifest. The container cannot tell which route will read its manifest.

Where these options matter, prefer forms that read the same everywhere: absolute
epoch-nanosecond Avro timestamps, and final channel names written into the data (column names,
Avro `channel`) rather than added by `channelPrefix`. Then confirm channel names, units and
videos after a representative ingest on the target deployment.

## Output file formats

- **Tabular**: CSV with a header row, or Parquet. One column holds timestamps; tag columns
  become tags; every other column becomes a channel.
- **Avro stream**: an Avro object container file whose records match the schema below
  (reproduced from `Dataset.add_avro_stream` in the Python SDK). Each record carries one
  channel, parallel `timestamps` and `values` arrays of equal length, and its own tags, so the
  format needs no tag columns. The `nominal-streaming` Rust crate and Python package write this
  schema to a local file (`stream_to_file` / `to_file`) with Unix-epoch nanosecond timestamps;
  any Apache Avro library can write it from the schema.
- **Journal JSON**: one JSON object per line with a `MESSAGE` string and a timestamp field
  (numeric when declared per output). Other top-level fields become string log arguments. Lines
  missing either required field are skipped, and logs take neither tags nor a channel prefix.
- **Video**: one of the containers listed above, encoded as the camera recorded it.

```json
{
  "type": "record",
  "name": "AvroStream",
  "namespace": "io.nominal.ingest",
  "fields": [
    {"name": "channel", "type": "string"},
    {"name": "timestamps", "type": {"type": "array", "items": "long"}},
    {"name": "values", "type": {"type": "array", "items": [
      "double",
      "string",
      "long",
      {"type": "record", "name": "DoubleArray", "fields": [{"name": "items", "type": {"type": "array", "items": "double"}}]},
      {"type": "record", "name": "StringArray", "fields": [{"name": "items", "type": {"type": "array", "items": "string"}}]},
      {"type": "record", "name": "JsonStruct", "fields": [{"name": "json", "type": "string"}]}
    ]}},
    {"name": "tags", "type": {"type": "map", "values": "string"}, "default": {}}
  ]
}
```

Struct values are JSON strings wrapped in `JsonStruct`. A file that does not follow this schema
fails ingestion.

## Timestamp metadata precedence

This section is authoritative for timestamp precedence; see
[modeling](modeling.md#timestamps-choose-from-evidence) for choosing the clock model.

| Precedence | Level | Set by | Supports |
|---|---|---|---|
| 1 (highest) | Per output | `timestampMetadata` in `manifest.json` | Numeric epoch or relative only |
| 2 | Ingest request | `timestamp_column`/`timestamp_type` on `add_containerized` | Every type, including ISO 8601 and custom formats |
| 3 (lowest) | Image default | `default_timestamp_column`/`default_timestamp_type` at registration | Every type |

The platform resolves levels 2 and 3 before the container starts and fails the job if both are
absent, even when the manifest describes every output. SDK and CLI registration require a
default; images from older registration paths may lack one and then need an override on every
ingest. The resolved value is what `_NOMINAL_TIMESTAMP_METADATA` carries. An Avro output that
inherits must inherit a numeric type, because its timestamps are integers. Never register a
relative default with a fixed start: every future upload would inherit that start. Supply a
capture's start per output or per ingest instead.

## Check conformance locally

Run the built image the way the platform does: amd64, an arbitrary non-root UID, an empty
writable `/home` as `$HOME` (hiding anything the image put there), read-only inputs, and a
file standing in for the termination log. On Linux
hosts, make `out/` and `termination.log` writable by that UID first (for example,
`chmod 777 out` and `chmod 666 termination.log`).

```sh
mkdir -p out && : > termination.log
docker run --rm --platform linux/amd64 --user 12345:12345 \
  --tmpfs /home:exec,mode=1777 -e HOME=/home \
  -v "$PWD/testdata:/input:ro" -v "$PWD/out:/output" \
  -v "$PWD/termination.log:/dev/termination-log" \
  -e OUTPUT_DIR=/output -e RAW_FILE=/input/capture.bin -e THRESHOLD=0.9 \
  my-extractor:0.3.0-g1a2b3c4-b42
echo "exit status: $?"
```

On success, check that `out/manifest.json` parses, uses only the field names above, names only
files that exist with extensions matching their `ingestType`, and does not list itself. Then
decode the outputs and check values, units and timestamps as in
[authoring](authoring.md#test-what-the-data-means). On failure, check that the exit status is
the one registered for that failure class and that `termination.log` holds a single JSON
document under 4,096 bytes whose `code` is not platform-reserved. Rerun without the
`_NOMINAL_*` variables and again with representative ones, since the platform may or may not
inject them.
