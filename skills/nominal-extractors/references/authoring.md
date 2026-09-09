# Authoring extractor code

Everything here runs *inside* the container, using `nominal.experimental.extractor`. The
container needs `nominal` installed plus whatever format libraries your code uses (`pyarrow`,
`pandas`, ...); format I/O is your own dependency, and the runtime only manages the contract
with the ingest pipeline.

## The environment contract

Nominal drives the container entirely through the environment: each input file is mounted
under `/input` with its path also in the environment variable declared for it at
registration; output goes to `$OUTPUT_DIR`; parameters arrive as environment-variable
strings; and `_NOMINAL_*` variables carry the registered contract plus, on newer platforms,
system metadata (job and dataset RIDs, resolved timestamp metadata, tags).

Never read these directly. The context object (`ctx`) resolves all of it, and the `_NOMINAL_*`
ones are absent on local runs.

## Entrypoint

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
so `logging` output lands in the job's captured logs. Prefer `logging` over `print`, and keep
it sparse: the capture is capped at 1 MiB per job, so a per-row log can push your own
traceback out of it.

## Reading inputs and parameters

```python
ctx.inputs                       # list[Path]: every mounted input file
ctx.input()                      # Path: the sole input (raises unless exactly one)
ctx.input("RAW_FILE")            # Path: by env variable, or registered display name

ctx.param("THRESHOLD")           # str: raises ExtractorError if unset
ctx.get_param("PARTS", "2")      # str: default when unset
ctx.get_param("MAYBE")           # str | None
```

Values are always strings — coerce yourself: `int(ctx.get_param("PARTS", "2"))`.

Names resolve against the registered contract when it's present (a real run): the display
name or the environment variable both work, and an unknown name raises `ExtractorError`
listing the valid ones — for a parameter that's an authoring bug, not a missing value. On
local runs, with no injected metadata, `ctx.input("NAME")` and the param lookups read the
environment variable `NAME` directly, and `ctx.inputs` lists the input directory (default
`/input`, overridable with `NOMINAL_EXTRACTOR_INPUT_DIR`).

An optional input the request didn't provide is *not* among the run's inputs — probe
`ctx.inputs` or catch `ExtractorError` where an input may legitimately be absent.

## System metadata

All optional; `None` or empty on local runs.

```python
ctx.ingest_job_rid          # str | None
ctx.dataset_rid             # str | None
ctx.additional_tags         # dict[str, str]: tags the ingest request applies to all data
ctx.job_timestamp_metadata  # TimestampMetadata | None: the job-level default outputs inherit
```

## Declaring outputs — manifest mode

The contract new extractors use, for images registered `MANIFEST`. Declare each file with the
method for its format; the runtime writes `manifest.json` from the declarations when your
function returns. At least one declaration is required.

```python
ctx.add_tabular(
    path,                                    # .csv or .parquet under ctx.output_dir
    tag_columns={"vehicle": "vehicle_id"},   # tag name -> column carrying its values
    channel_prefix="engine",                 # prepended to every channel from this file
    timestamp_column="time_ns",              # with timestamp_type, overrides job-level metadata
    timestamp_type="epoch_nanoseconds",
)

ctx.add_avro_stream(
    path,                                    # .avro or .avro.gz
    channel_prefix="bus",
    timestamp_type="epoch_nanoseconds",      # how to read the schema's timestamps field
)

ctx.add_journal_json(
    path,                                    # .jsonl or .jsonl.gz, ingested as logs
    timestamp_column="ts",                   # top-level JSON field holding each line's timestamp
    timestamp_type="epoch_seconds",
)

ctx.add_video(
    path,                                    # a supported container (e.g. .mp4) under output_dir
    channel="camera/front",
    start=recording_started_at,              # OR frame_timestamps=[...] (exactly one)
)
```

Format-specific rules:

- **`add_tabular`** — columns become channels. `timestamp_column` and `timestamp_type` must
  be passed together or not at all (the overloads make a half-pair a type error).
- **`add_avro_stream`** — records carry their own channel, values, and tags, so there are no
  tag columns and no timestamp column: the schema fixes which field holds timestamps
  (`timestamps`), and `timestamp_type` only says how to read the numbers in it. Omitting it
  inherits the job-level metadata, which is correct only when that metadata is numeric — avro
  timestamps are integers, and a string format can't read them.
- **`add_journal_json`** — each line needs a `MESSAGE` field and a timestamp field; lines
  missing either are skipped. Other top-level fields become stringified log args. Takes
  neither tag columns nor a channel prefix.
- **`add_video`** — exactly one of `start` (absolute start; frame times come from the video's
  encoded presentation timestamps) or `frame_timestamps` (one absolute nanosecond timestamp
  per frame, whose sidecar file the runtime writes and declares for you). With `start`, at
  most one of `ending_timestamp`, `true_frame_rate`, `scale_factor` corrects a playback-rate
  mismatch. Requires a recent platform version: an older ingest pipeline ignores video
  outputs and rejects a manifest whose only outputs are videos.
- Declaring the same file twice is allowed, and each declaration becomes its own manifest
  entry — e.g. one table ingested under two timestamp columns.

Per-output timestamp metadata supports **numeric types only**: `"epoch_seconds"`,
`"epoch_milliseconds"`, `"epoch_microseconds"`, `"epoch_nanoseconds"`, or the typed
`ts.Epoch(unit=...)` / `ts.Relative(unit=..., start=...)`. An output needing ISO 8601 or a
custom format must omit the pair and inherit the job-level metadata, which supports the full
range. Resolution order per file: per-output metadata → the ingest request's override → the
image's registered default. The override-or-default part is resolved *before* the container
runs and ingestion fails if both are absent, which is why registration always requires a
default. See `modeling.md` for the choice this machinery exists to serve.

## Declaring outputs — single-file mode

The original contract, for images registered `PARQUET`, `CSV`, or `AVRO_STREAM`: exactly one
output file, parsed per the registered format. For maintaining an image already registered
this way — write new extractors as manifest extractors.

```python
@single_file_extractor
def convert(ctx: SingleFileExtractorContext) -> None:
    out = ctx.output_dir / "converted.parquet"
    write_parquet(read_input(ctx.input()), out)
    ctx.set_output(out)
```

`set_output` records a file you already wrote under `ctx.output_dir`; a second call raises,
and producing no output fails the run. Everything else — timestamps, tag columns, channel
prefixes — comes from the job-level metadata, which is the main reason not to start here.

## Error semantics

- **`ExtractorError`** — violations of the extractor contract: missing required parameter,
  unknown input name, output outside `output_dir`, the reserved `manifest.json` name, a
  timestamp unit the manifest can't express.
- **`ValueError` and friends** — malformed arguments, *and a file extension the declaration
  method can't read*. `ExtractorError` subclasses `NominalError`, not `ValueError`, so the two
  are disjoint: `except ExtractorError` around a declaration will not catch an extension
  mismatch. Catch both, or neither.
- Anything escaping your function prints a traceback and exits non-zero, failing the job.
  That is the correct way to fail — never catch broadly to keep going, because an empty
  dataset under a green job is much worse than a red job.

Decide deliberately what a degenerate input means. The runtime accepts both answers: a
declared zero-row table is a legitimate output, so an empty source can succeed and add
nothing. Raising is usually better for exactly that reason — take the zero-row path only
where "this capture is legitimately empty" is an expected state, not a symptom.

The runtime also logs advisory warnings — at startup for a registered-required parameter with
no value or a registered input that isn't mounted, and at finalize for undeclared files left
in the output directory. They usually point straight at the bug.

## Local testing

`Extractor.run` takes an explicit environment, so extractors are testable without Docker or
platform access:

```python
def test_convert(tmp_path):
    raw = tmp_path / "raw.bin"
    raw.write_bytes(make_test_frames())
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    ctx = convert.run(
        env={
            "OUTPUT_DIR": str(out_dir),
            "RAW_FILE": str(raw),   # local runs read input env vars directly
            "THRESHOLD": "0.9",
        },
        exit=False,                 # re-raise failures instead of sys.exit(1)
    )

    table = pq.read_table(out_dir / "telemetry.parquet")
    assert table.num_rows > 0
```

- **`env` replaces the environment, it does not merge.** What you pass is the entire
  environment the run sees, so it must carry `OUTPUT_DIR`, every input, and every parameter
  the code reads; nothing is inherited from the ambient process. Omitting `OUTPUT_DIR` raises
  `ExtractorError` rather than falling back to a real value — the most common way a local
  test fails before it tests anything.
- `exit=False` returns the context on success and re-raises on failure, so failure tests can
  assert on the exception.
- In manifest mode, assert on `ctx.build_manifest()` — the manifest document exactly as
  written — rather than re-parsing `manifest.json`.
- To exercise the *registered-contract* paths (display-name resolution, unknown-name errors),
  inject the metadata Nominal would — `_NOMINAL_OUTPUT_FORMAT="MANIFEST"` plus
  `_NOMINAL_INPUTS='[{"name": "Raw file", "environmentVariable": "RAW_FILE", "path": "/tmp/raw.bin"}]'`
  and `_NOMINAL_PARAMETERS='[{"name": "Quality threshold", "environmentVariable": "THRESHOLD", "required": false}]'`.
- After building, a dress rehearsal under Docker exercises the image itself:

  ```sh
  docker run --rm \
    -v "$PWD/testdata:/input:ro" -v "$PWD/out:/output" \
    -e OUTPUT_DIR=/output -e RAW_FILE=/input/raw.bin -e THRESHOLD=0.9 \
    my-extractor:0.1.0
  ```
