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

Use the context object (`ctx`) to resolve these values. Platform-injected `_NOMINAL_*`
metadata is absent on ordinary local runs unless the test explicitly supplies it.

The container runs as a non-root user; `$OUTPUT_DIR` is writable, and `$HOME` is writable but
starts empty on every job. Put scratch files under one of those rather than beside the code,
and see [registration](registration.md#build-and-verify-amd64) for what an empty `$HOME`
means when installing dependencies into the image.

## Entrypoint and startup checks

This is a scaffold, not an implemented parser: replace the explicit placeholder with parsing
validated against the agreed contract.

```python
from nominal.experimental.extractor import ManifestExtractorContext, manifest_extractor

@manifest_extractor
def my_extractor(ctx: ManifestExtractorContext) -> None:
    raise NotImplementedError("Implement and validate the source-format parser")

if __name__ == "__main__":
    my_extractor.run()
```

`run()` builds the context from the environment, validates the registered contract, calls
your function, finalizes outputs (writing `manifest.json` in manifest mode), and turns any
failure — including a `SystemExit` from your code — into a non-zero exit so the ingest job
fails cleanly. As a real entrypoint it also calls `logging.basicConfig(level=logging.INFO)`,
so `logging` output lands in the job's captured logs. Prefer `logging` over `print`, and keep
it sparse: the capture is capped at 1 MiB per job, so a per-row log can push your own
traceback out of it. Log aggregate accepted, filtered and rejected counts, not rows.

At startup the runtime rejects a manifest/single-file decorator mismatch with the registered
output format. Missing mounted inputs and required parameters earn advisory warnings; they
do not guarantee an early failure. Read required inputs and coerce/validate essential
parameters before doing expensive parsing. With no registered metadata, local runs do not
exercise these contract checks.

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

All optional; `None` or empty when not injected, as in ordinary local runs.

```python
ctx.ingest_job_rid          # str | None
ctx.dataset_rid             # str | None
ctx.additional_tags         # dict[str, str]: tags the ingest request applies to all data
ctx.job_timestamp_metadata  # TimestampMetadata | None: the job-level default outputs inherit
```

## Declaring outputs — manifest mode

The contract new extractors use, for images registered `MANIFEST`. Declare each file with the
method for its format; the runtime writes `manifest.json` from the declarations when your
function returns. At least one declaration is required. Write files beneath `ctx.output_dir`
and declare them; undeclared files are warned about and not ingested. `manifest.json` is
reserved for the runtime.

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

## Timestamp metadata contract

This section is authoritative for metadata types and precedence; see
[modeling](modeling.md#timestamps-choose-from-evidence) for choosing the source clock model.

| Location | Supported timestamp types |
|---|---|
| Manifest tabular/log declaration | Numeric `ts.Epoch(unit=...)`, `ts.Relative(unit=..., start=...)`, or `"epoch_seconds"` / `"epoch_milliseconds"` / `"epoch_microseconds"` / `"epoch_nanoseconds"`; column and type together, or neither. |
| Manifest Avro declaration | The same numeric types; no column argument, since the schema uses `timestamps`. |
| Ingest request / image default | Full timestamp types, including `ts.Iso8601()` and `ts.Custom(format=...)`; string types cannot interpret Avro's integer timestamps. |
| Video declaration | Its own start or per-frame timing contract described above. |

Per output, resolution is **manifest metadata → ingest request override → image default**.
To preserve absolute strings, omit the per-output timestamp pair and inherit matching
request/default metadata. The platform resolves request override or image default *before*
running the container and fails if both are absent, even with a fully described manifest.
SDK registration requires a default; older registration paths may have images without one,
which require an override on every ingest. Never use a fixed capture start as an image default.

`ctx.job_timestamp_metadata` exposes the resolved job default when injected. Ordinary local
runs have none and can still finalize outputs; that success does not prove the platform has
required timestamp metadata. Keep capture-specific starts in the manifest or ingest request,
and verify decoded absolute bounds in local checks and after real ingestion.

## Declaring outputs — single-file mode

The original contract, for images registered `PARQUET`, `CSV`, or `AVRO_STREAM`: exactly one
output file, parsed per the registered format. For maintaining an image already registered
this way — write new extractors as manifest extractors.

Illustrative only: `read_input` and `write_parquet` below are project parser/writer placeholders.

```python
from nominal.experimental.extractor import SingleFileExtractorContext, single_file_extractor

@single_file_extractor
def convert(ctx: SingleFileExtractorContext) -> None:
    out = ctx.output_dir / "converted.parquet"
    write_parquet(read_input(ctx.input()), out)
    ctx.set_output(out)
```

`set_output` records a file you already wrote under `ctx.output_dir`; a second call raises,
and producing no output fails the run. There are no per-output timestamp, tag-column or
channel-prefix controls here. Timestamps inherit the job default; upload tags are a separate
ingest-request argument, not fields of `TimestampMetadata`.

## Error semantics

- **`ExtractorError`** — violations of the extractor contract: missing required parameter,
  unknown input name, output outside `output_dir`, the reserved `manifest.json` name, a
  timestamp unit the manifest can't express.
- **`ValueError` and friends** — malformed arguments, *and a file extension the declaration
  method can't read*. `ExtractorError` subclasses `NominalError`, not `ValueError`, so the two
  are disjoint: `except ExtractorError` around a declaration will not catch an extension
  mismatch. Catch both, or neither.
- Anything escaping your function prints a traceback and exits non-zero, failing the job.
  Let unexpected failures propagate. Only catch known record errors where the agreed policy
  permits partial results; count rejections and report the reasons.

Implement the agreed empty/malformed/filtering policy from [modeling](modeling.md). A declared
zero-row table can satisfy the runtime output contract; this does not establish a meaningful
capture. Distinguish empty source, all-filtered data and malformed records, and assert the
intended result for each rather than quietly returning a green empty output.

The runtime also logs advisory warnings — at startup for a registered-required parameter with
no value or a registered input that isn't mounted, and at finalize for undeclared files left
in the output directory. They usually point straight at the bug.

## Local testing

`Extractor.run` takes an explicit environment, so extractors are testable without Docker or
platform access:

The example assumes a project `convert_manifest` function decorated with `@manifest_extractor`,
a representative `raw_file` fixture, and an existing `out_dir` directory. It demonstrates the
invocation, not a complete parser or sufficient test:

```python
ctx = convert_manifest.run(
    env={
        "OUTPUT_DIR": str(out_dir),
        "RAW_FILE": str(raw_file),
        "THRESHOLD": "0.9",
    },
    exit=False,
)
manifest = ctx.build_manifest()
```

Read the generated files and check selected expected values, channel names, units/conversions,
and preserved timestamp precision. Decode timestamps with the declared metadata and check
absolute start/end bounds against the fixture's known capture, including resets or malformed
times. Check declared paths, formats, timestamp fields, tag-to-column mappings, actual tag
values and consumed columns. Exercise missing parameters/IDs, malformed records, empty and
all-filtered input, and rejection/filter counts according to the contract. Row count alone is
insufficient. Use existing project tests/fixtures where practical.

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
    my-extractor:0.3.0-g1a2b3c4-b42
  ```
