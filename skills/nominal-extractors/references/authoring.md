# Authoring extractor code

Everything here runs *inside* the container, using `nominal.experimental.extractor`. The
container needs `nominal` installed plus whatever format libraries your code uses (`pyarrow`,
`pandas`, ...). Format I/O is your own dependency; the runtime only manages the contract with
the ingest pipeline.

## The environment contract

Nominal drives the container entirely through the environment:

- Each input file is mounted under `/input`, and its path is also exposed in the
  environment variable declared for that input at registration time.
- Output goes to the directory named by `$OUTPUT_DIR`.
- Declared parameters arrive as environment variables; values are always strings.
- Nominal also injects `_NOMINAL_*` metadata describing the registered contract (output
  format, inputs, parameters) and, on newer platforms, system metadata (job and dataset RIDs,
  resolved timestamp metadata, tags). All optional, and absent on local runs.

Never read these variables directly. The context object (`ctx`) resolves all of it.

## Entrypoint shape

```python
from nominal.experimental.extractor import ManifestExtractorContext, manifest_extractor

@manifest_extractor
def my_extractor(ctx: ManifestExtractorContext) -> None:
    ...

if __name__ == "__main__":
    my_extractor.run()
```

`run()` builds the context from the environment, validates the registered contract, calls
your function, finalizes outputs (writing `manifest.json` in manifest mode), and turns any
failure — including a `SystemExit` from your code — into a non-zero exit so the ingest job
fails cleanly. As a real entrypoint it also calls `logging.basicConfig(level=logging.INFO)`,
so `logging` output lands in the job's captured logs. Prefer `logging` over `print` for
anything you will want when debugging a failed job.

Exports from `nominal.experimental.extractor`:
`single_file_extractor`, `manifest_extractor`, `Extractor`, `ExtractorContext`,
`SingleFileExtractorContext`, `ManifestExtractorContext`, `ExtractorError`,
`TimestampMetadata`.

## Reading inputs

```python
ctx.inputs                # list[Path]: every mounted input file
ctx.input()               # Path: the sole input (raises unless exactly one)
ctx.input("RAW_FILE")     # Path: by env variable, or registered display name
```

With registered contract metadata present (a real run), `ctx.input(name)` accepts the
input's registered display name or its environment variable; an unknown name raises
`ExtractorError` listing the valid ones. An optional input the ingest request didn't
provide is *not* among the run's inputs — probe `ctx.inputs` or catch `ExtractorError`
if an input may legitimately be absent.

On local runs (no injected metadata), `ctx.input("NAME")` reads the environment variable
`NAME` directly, and `ctx.inputs` lists the input directory (default `/input`, overridable
via `NOMINAL_EXTRACTOR_INPUT_DIR`).

## Reading parameters

```python
ctx.param("THRESHOLD")           # str: raises ExtractorError if unset
ctx.get_param("PARTS", "2")      # str: default when unset
ctx.get_param("MAYBE")           # str | None
```

Values are always strings — coerce yourself: `int(ctx.get_param("PARTS", "2"))`. Names
resolve like inputs do (registered display name or env variable; env variable directly on
local runs). With contract metadata present, an unregistered name raises `ExtractorError`
— it's an authoring bug, not a missing value.

## System metadata (all optional; None/empty on local runs)

```python
ctx.ingest_job_rid          # str | None
ctx.dataset_rid             # str | None
ctx.additional_tags         # dict[str, str]: tags the ingest request applies to all data
ctx.job_timestamp_metadata  # TimestampMetadata | None: the job-level default your outputs inherit
```

## Declaring outputs — manifest mode

The contract new extractors use, for images registered with output format `MANIFEST`.
Declare each file with the method for its format; the runtime writes `manifest.json` from
the declarations when your function returns. At least one declaration is required.

```python
ctx.add_tabular(
    path,                          # .csv or .parquet under ctx.output_dir
    tag_columns={"vehicle": "vehicle_id"},   # tag name -> column carrying its values
    channel_prefix="engine",       # prepended to every channel from this file
    timestamp_column="time_ns",    # with timestamp_type, overrides job-level metadata
    timestamp_type="epoch_nanoseconds",
)

ctx.add_avro_stream(
    path,                          # .avro or .avro.gz
    channel_prefix="bus",
    timestamp_type="epoch_nanoseconds",  # how to read the schema's timestamps field
)

ctx.add_journal_json(
    path,                          # .jsonl or .jsonl.gz, ingested as logs
    timestamp_column="ts",         # top-level JSON field holding each line's timestamp
    timestamp_type="epoch_seconds",
)

ctx.add_video(
    path,                          # a supported video container (e.g. .mp4) under ctx.output_dir
    channel="camera/front",
    start=recording_started_at,    # OR frame_timestamps=[...] (exactly one of the two)
)
```

Format-specific rules:

- **`add_tabular`**: columns become channels. `timestamp_column`/`timestamp_type` must be
  passed together or not at all (the overloads make a half-pair a type error).
- **`add_avro_stream`**: avro records carry their own channel, values, and tags, so there
  are no tag columns and no timestamp column — the schema fixes which field holds
  timestamps (`timestamps`); `timestamp_type` only says how to read the numbers in it.
  Omitting it inherits the job-level metadata, which is only correct when that metadata is
  numeric (avro timestamps are integers; a string format can't read them).
- **`add_journal_json`**: each line needs a `MESSAGE` field and a timestamp field; lines
  missing either are skipped. Other top-level fields become log args (stringified). Log
  outputs take neither tag columns nor a channel prefix.
- **`add_video`**: exactly one of `start` (absolute start; frame times come from the
  video's encoded presentation timestamps) or `frame_timestamps` (one absolute nanosecond
  timestamp per frame — the runtime writes and declares the sidecar file for you). With
  `start`, at most one of `ending_timestamp`, `true_frame_rate`, `scale_factor` corrects
  playback-rate mismatch. Requires a recent platform version: an older ingest pipeline
  ignores video outputs and rejects a manifest whose only outputs are videos.
- Declaring the same file more than once is allowed and each declaration becomes its own
  manifest entry (e.g. one table ingested under two timestamp columns).

## Timestamp metadata in outputs

Per-output timestamp metadata supports **numeric types only**: string literals
`"epoch_seconds"`, `"epoch_milliseconds"`, `"epoch_microseconds"`, `"epoch_nanoseconds"`,
or the typed forms `ts.Epoch(unit=...)` / `ts.Relative(unit=..., start=...)`, with units
seconds through nanoseconds. Outputs needing ISO 8601 or custom formats must omit the
per-output pair and rely on the job-level metadata (the ingest request override or the
image's registered default), which supports the full range.

Resolution order per output file: per-output manifest metadata → ingest request override
→ image default. The override-or-default portion is resolved *before* the container runs
and ingestion fails if both are absent — so registration always requires a default.

See `modeling.md` for choosing between absolute and relative time, which is the decision
this machinery exists to serve.

## Declaring outputs — single-file mode

The original contract, for images registered with output format `PARQUET`, `CSV`, or
`AVRO_STREAM`: the pipeline ingests exactly one output file, parsed per the registered
format. You need this when maintaining an image already registered that way; write new
extractors as manifest extractors instead.

```python
@single_file_extractor
def convert(ctx: SingleFileExtractorContext) -> None:
    out = ctx.output_dir / "converted.parquet"
    write_parquet(read_input(ctx.input()), out)
    ctx.set_output(out)
```

`set_output` records a file you already wrote under `ctx.output_dir`; a second call
raises. Producing no output fails the run. There is no per-output timestamp, tag-column, or
channel-prefix control in this mode — everything comes from the job-level metadata, which
is the main reason not to start here.

## Error semantics

- `ExtractorError` (from `nominal.experimental.extractor`) — violations of the extractor
  contract: missing required parameter, unknown input name, output outside `output_dir`,
  reserved `manifest.json` name, a timestamp unit the manifest can't express.
- `ValueError` and friends — malformed arguments, *and a file extension the declaration
  method can't read*, same as the rest of the SDK. `ExtractorError` subclasses `NominalError`,
  not `ValueError`, so the two are disjoint: `except ExtractorError` around a declaration will
  not catch the extension mismatch. Catch both, or neither and let `run()` fail the job.
- Any exception escaping your function or the runtime prints a traceback and exits non-zero,
  failing the ingest job. That is the correct way to fail. Do not catch broad exceptions to
  keep going: an empty dataset under a green job status is much worse than a red job.

Decide deliberately what a degenerate input means. An empty or truncated source file can
either raise or produce a valid zero-row output, and the runtime accepts both — a declared
zero-row table is a legitimate output, so the job succeeds and the dataset gains nothing.
Raising is usually the better default for that reason: a green job that ingested nothing is
the hardest failure for an uploader to notice, while a red job names itself. Use the zero-row
path only where "this capture is legitimately empty" is an expected state, not a symptom.

The runtime also logs advisory warnings at startup (a registered-required parameter unset, a
registered input missing from the mount) and at finalize (undeclared files left in the output
directory). Watch for these in job logs; they usually point straight at the bug.

## Local testing

`Extractor.run` takes an explicit environment, so extractors are testable without Docker
or platform access:

```python
def test_convert(tmp_path):
    raw = tmp_path / "raw.bin"
    raw.write_bytes(make_test_frames())
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    ctx = convert.run(
        env={
            "OUTPUT_DIR": str(out_dir),
            "RAW_FILE": str(raw),        # local runs read input env vars directly
            "THRESHOLD": "0.9",
        },
        exit=False,                       # re-raise failures instead of sys.exit(1)
    )

    table = pq.read_table(out_dir / "telemetry.parquet")
    assert table.num_rows > 0
```

Notes:

- **`env` replaces the environment, it does not merge into it.** The mapping you pass is the
  entire environment the run sees, so it must carry `OUTPUT_DIR`, every input, and every
  parameter the code reads. Nothing is inherited from the ambient process. Omitting
  `OUTPUT_DIR` raises `ExtractorError` instead of falling back to a real value — the most
  common way a local test fails before it tests anything.
- `run(..., exit=False)` returns the context on success and re-raises on failure. Assert on
  the exception in failure tests.
- In manifest mode, `ctx.build_manifest()` returns the manifest document exactly as written.
  Assert on that rather than re-parsing `manifest.json`.
- To exercise the *registered-contract* code paths (display-name resolution, unknown-name
  errors), inject the metadata Nominal would:
  `_NOMINAL_INPUTS='[{"name": "Raw file", "environmentVariable": "RAW_FILE", "path": "/tmp/raw.bin"}]'`,
  `_NOMINAL_PARAMETERS='[{"name": "Quality threshold", "environmentVariable": "THRESHOLD", "required": false}]'`,
  `_NOMINAL_OUTPUT_FORMAT="MANIFEST"`.
- After building the image, a full dress rehearsal under Docker:

  ```sh
  docker run --rm \
    -v "$PWD/testdata:/input:ro" -v "$PWD/out:/output" \
    -e OUTPUT_DIR=/output -e RAW_FILE=/input/raw.bin -e THRESHOLD=0.9 \
    my-extractor:0.1.0
  ```
