# Authoring extractor code

Two paths implement the same [container contract](contract.md). Choose by the parser, not the
SDK: the Python framework when the parser is or can be Python, and a direct implementation for
anything else, including a wrapper around an existing binary. Format I/O is the project's own
dependency either way; the contract only governs the boundary with the ingest pipeline.

## Shape every entrypoint the same way

1. Resolve and validate every input and parameter before expensive work: required values
   present, paths are files, parameters coerce and fall in range.
2. Parse, streaming where inputs are large; memory is limited.
3. Write outputs under `$OUTPUT_DIR` and scratch files under `$HOME`.
4. Declare each output once it is complete; in manifest mode `manifest.json` comes last.
5. Map each expected failure class to a stable code and exit status, and let unexpected
   failures surface as a generic failure with a stack trace on stderr.
6. Log aggregate accepted, filtered and rejected counts with reasons, not rows: the log
   capture keeps only the first 1 MiB per attempt, so per-row logging pushes the traceback
   out of it.

## Python: the extractor framework

Use `nominal>=1.171` in the image; the declarative decorators arrived in 1.170 and per-output
units in 1.171. The package README (`nominal/experimental/extractor/README.md` in the public
[nominal-client](https://github.com/nominal-io/nominal-client) repository) and the installed
docstrings are the complete reference. Read them when a detail here is missing rather than
guessing, and treat the API as experimental: it tracks the ingest pipeline's contract.

### Declare the entrypoint

Replace the placeholder with parsing validated against the agreed contract:

```python
from pathlib import Path

from nominal.experimental import extractor


class MalformedCaptureError(ValueError):
    """The capture does not decode as the agreed source format."""


@extractor.manifest_extractor(
    default_timestamp_column="time_ns",
    default_timestamp_type="epoch_nanoseconds",
)
@extractor.error(
    MalformedCaptureError,
    code="MALFORMED_INPUT",
    exit_code=64,
    message="The capture could not be decoded.",
)
@extractor.error(
    extractor.ExtractorError,
    code="EXTRACTOR_CONTRACT",
    exit_code=78,
    message="The extractor inputs, parameters or outputs violated its contract.",
)
@extractor.input("raw_file", name="Raw file", file_suffixes=["bin"], description="ACME logger capture")
@extractor.input("channel_map", default=None, file_suffixes=["json"])
@extractor.parameter(
    "threshold",
    name="Quality threshold",
    type=extractor.FloatRange(min=0.0, max=1.0),
    default=0.9,
    description="Drop samples below this quality, 0-1 (default 0.9)",
)
def convert(
    ctx: extractor.ManifestExtractorContext,
    *,
    raw_file: Path,
    channel_map: Path | None,
    threshold: float,
) -> None:
    raise NotImplementedError("Implement and validate the source-format parser")


if __name__ == "__main__":
    convert.run()
```

- Keep the extractor decorator outermost; `@input`, `@parameter` and `@error` go beneath it in
  any order. Registration lists follow their top-to-bottom order.
- Each declaration names a callback argument and defaults its environment variable to the
  uppercase name (`raw_file` → `RAW_FILE`); override with `envvar=` to preserve an existing
  name. `name=` and `description=` are what uploaders see.
- The callback takes `ctx` first, then keyword-only arguments with no signature defaults.
  Defaults live in the decorators, and every argument needs a declaration.
- Keep `.run()` under the `__main__` guard so registration code can import the module
  without running extraction.

`run()` builds the context from the environment, checks the decorator against
`_NOMINAL_OUTPUT_FORMAT`, binds every declared argument, calls the function, finalizes outputs
(writing `manifest.json`), and turns any failure, including `SystemExit` from user code, into
a non-zero exit. As the entrypoint it also configures `logging` at INFO, so prefer `logging`
over `print`.

### Inputs and parameters

- Arguments are required unless the decorator supplies a default. An optional input uses
  `default=None` and arrives as `Path | None`; a supplied input path must exist as a file.
- `@parameter(type=...)` converts the supplied string. Without `type=`, a `str`, `int`,
  `float` or `bool` default selects the converter; otherwise values stay `str`. Defaults are
  already-converted values (`default=2`, not `"2"`); `default=None` makes a parameter optional
  without inferring a converter, so pair it with `type=`.
- Booleans accept `true/false`, `yes/no`, `on/off` and `1/0`, case-insensitively. Floats reject
  NaN and infinity. An empty string is a supplied value, not a request for the default.
- `extractor.Choice([...])` (exact, case-sensitive), `extractor.IntRange(min=, max=)` and
  `extractor.FloatRange(min=, max=)` (inclusive) express common constraints. In a custom
  converter, raise `extractor.BadParameter("must be a positive odd integer")` for a message safe
  to show users. A plain `ValueError` or `TypeError` is reported without its message or the
  supplied value; any other exception propagates unchanged, so wrap third-party parse errors.
- Every argument resolves before the callback runs. Binding failures raise `ExtractorError` and
  pass through the same `@error` mappings as extraction failures.
- When `_NOMINAL_*` metadata is present it is authoritative and matched by environment
  variable, not display name: a parameter the registered image lacks is a contract error even
  when its decorator has a default. Local runs without metadata read the variables directly.

Registration records names, descriptions, environment variables, suffixes and requiredness.
Converters and defaults stay in code, so put accepted values, units and the default in the
parameter's `description=`, where uploaders can see them.

### Job metadata

All optional; `None` or empty on ordinary local runs:

```python
ctx.ingest_job_rid          # str | None
ctx.dataset_rid             # str | None
ctx.additional_tags         # dict[str, str]: the ingest request's tags
ctx.job_timestamp_metadata  # TimestampMetadata | None: what outputs without their own metadata inherit
```

### Declare outputs (manifest mode)

Write each file beneath `ctx.output_dir`, then declare it with the method for its format. Each
call maps one-to-one to a `manifest.json` entry described in the
[contract](contract.md#manifestjson), and checks the file's extension immediately.

```python
ctx.add_tabular(
    table_path,                             # .csv or .parquet (optionally .gz)
    tag_columns={"motor": "motor_id"},      # tag name -> column carrying its values
    channel_prefix="engine.",
    units={"engine.pressure": "kPa"},       # keyed by final channel name, after the prefix
    timestamp_column="elapsed_us",          # column and type together, or neither
    timestamp_type=ts.Relative("microseconds", start=capture_start),
)
ctx.add_avro_stream(records_path, units={"voltage": "V"}, timestamp_type="epoch_nanoseconds")
ctx.add_journal_json(events_path, timestamp_column="ts", timestamp_type="epoch_seconds")
ctx.add_video(video_path, channel="camera/front", start=capture_start)
```

(`ts` is `from nominal import ts`.)

- **`add_tabular`**: columns become channels. `timestamp_column` and `timestamp_type` go
  together; the overloads make a half-pair a type error.
- **`add_avro_stream`**: records carry their own channel, values and tags, so there are no tag
  columns or timestamp column. `timestamp_type` says how to read the schema's `timestamps`
  field; omitting it inherits the job-level metadata, which is correct only when that is
  numeric. `nominal_streaming.NominalDatasetStream().to_file(path)` writes the schema with
  epoch-nanosecond timestamps.
- **`add_journal_json`**: each line needs `MESSAGE` and a timestamp field. It takes neither tag
  columns nor a channel prefix.
- **`add_video`**: exactly one of `start` (an absolute start applied to the video's own
  presentation timestamps, correctable with at most one of `ending_timestamp`,
  `true_frame_rate` or `scale_factor`) or `frame_timestamps` (one absolute nanosecond per frame;
  the runtime writes and declares the sidecar). Timestamps accept a `datetime`, an ISO 8601
  string or integer nanoseconds.
- Prefixes, units, videos and Avro timestamp types depend on the deployment's ingest route;
  see [deployment differences](contract.md#deployment-differences).
- Declaring one file twice creates two entries, e.g. one table under two timestamp columns.
  At least one declaration is required, undeclared files draw a warning and are not ingested,
  and `manifest.json` is reserved for the runtime.

### Single-file mode (legacy)

Only for maintaining images registered `PARQUET`, `CSV` or `AVRO_STREAM`: declare
`@extractor.single_file_extractor(output_format=FileOutputFormat.PARQUET, ...)` (import it from
`nominal.core`), write one file, and record it with `ctx.set_output(path)`. A second call
raises and producing no output fails the run. There are no per-output timestamp, tag-column,
channel-prefix or unit controls. `output_format` is needed to export registration metadata
and is checked against the registered format at runtime.

### Structured failures

`@extractor.error(ExceptionType, code=..., exit_code=..., message=..., retryable=False)`
declares an expected failure. It covers startup, binding, extraction and finalization; the
nearest mapped class in the exception's method resolution order wins, and each class may be
declared once. On a match, `run()` writes `{"code", "message", "retryable"}` to
`/dev/termination-log` and stderr, with `message` taken from `str(exception)` and shortened to
fit 4,096 bytes, prints the traceback, and exits with `exit_code`. Unmapped failures print the
traceback and exit 1.

- `message=` is static fallback text. It becomes the image's registered exit-code mapping and
  is required for `registration_kwargs()`, but does not replace the runtime message.
- Map `ExtractorError` to its own configuration or contract code, separate from data errors,
  so a deployment fault never reports as bad input. Raise specific application exceptions for
  input problems so programming errors are not mislabeled.
- Codes must match `[A-Z][A-Z0-9_]*` and avoid the platform-reserved set; conflicting
  fallbacks for one exit code are rejected at export.
- Exception messages reach users through the job failure. Keep secrets and bulk raw values
  out of them.

### Error semantics

- **`ExtractorError`** covers extractor-contract violations: missing required input or
  parameter, an unregistered name, output outside `output_dir`, the reserved `manifest.json`
  name, an inexpressible timestamp unit.
- **`ValueError` and friends** cover malformed arguments, including an extension the
  declaration method cannot read. `ExtractorError` subclasses `NominalError`, not
  `ValueError`, so `except ExtractorError` around a declaration will not catch an extension
  mismatch.
- Let unexpected failures propagate. Catch known record errors only where the agreed policy
  permits partial results, and count rejections with their reasons.

Implement the agreed empty/malformed/filtering policy from [modeling](modeling.md). A
declared zero-row table satisfies the runtime but does not establish a meaningful capture;
distinguish empty source, all-filtered data and malformed records, and assert the intended
result for each.

To trace the framework itself, configure logging before `run()` and raise
`logging.getLogger("nominal.experimental.extractor")` to `DEBUG`. It logs context sources,
binding (names, never parameter values), finalization and error mapping.

### Migrating context lookups

`ctx.input()`, `ctx.inputs`, `ctx.param()` and `ctx.get_param()` still work but log one
migration warning per run and contribute nothing to `registration_kwargs()`. Move each lookup
into a declaration using the registered environment variable, preserving names, descriptions,
suffixes and requiredness:

| Existing lookup | Declaration and callback argument |
|---|---|
| `ctx.input("RECORDING")` | `@extractor.input("recording", envvar="RECORDING")`, `recording: Path` |
| `int(ctx.get_param("PARTS", "2"))` | `@extractor.parameter("parts", envvar="PARTS", type=int, default=2)`, `parts: int` |
| `ctx.get_param("LABEL")` | `@extractor.parameter("label", envvar="LABEL", default=None)`, `label: str \| None` |

Lookups by display name must map to the registered environment variable. Until every
dependency is declared, keep complete manually supplied registration metadata.

## Other languages: implement the contract directly

The entrypoint does the bookkeeping the Python runtime would. In outline:

```text
output_dir = env["OUTPUT_DIR"]                      or fail CONTRACT
raw_file   = env["RAW_FILE"], must be a file        or fail CONTRACT
threshold  = parse env.get("THRESHOLD", "0.9") in [0, 1]   or fail CONTRACT
if env has _NOMINAL_OUTPUT_FORMAT and it != "MANIFEST":    fail CONTRACT
optionally, if env has _NOMINAL_PARAMETERS / _NOMINAL_INPUTS:
    a variable the code reads that the registered image lacks  ->  fail CONTRACT

manifest = {"outputs": [], "videoOutputs": []}
for each output produced by the parser:
    write it under output_dir; append its entry once the file is complete
write output_dir/manifest.json with a JSON encoder; exit 0

on an expected failure (code, exit_status, message):
    payload = {"code", "message", "retryable"} as JSON, <= 4096 bytes
    best-effort write payload to /dev/termination-log; print payload to stderr; exit exit_status
on anything else: print the stack trace to stderr; exit 1
```

- Build `manifest.json` and termination payloads with a JSON library, never string
  templates: paths and messages need escaping.
- Keep epoch nanoseconds in 64-bit integers end to end. A `float64` cannot hold present-day
  epoch nanoseconds exactly, and it is the only number type in JavaScript and the default in
  many JSON libraries; use `BigInt`/`int64`, or emit relative offsets or a coarser unit that
  fits.
- Make the termination-log path injectable by the test harness, as a function argument rather
  than an environment variable, so tests can capture the payload without `/dev`.
- Keep environment-variable names, error codes and exit statuses as constants in one module,
  and test them against the checked-in registration config (see
  [registration](registration.md)); the Python framework derives both from one declaration,
  but a direct implementation must check for drift itself.
- **CSV**: header row, stable column order, locale-independent numbers (`.` decimal, no
  thousands separators) printed with a round-trip-exact formatter. The contract fixes no
  spelling for missing or non-finite values; leave missing cells empty, and verify any NaN or
  infinity handling with a representative ingest. Prefer Parquet when exact column types
  matter.
- **Parquet**: an Apache Arrow or Parquet implementation (Rust `parquet`/`arrow`, Arrow Go,
  Arrow C++, parquet-java), with integer timestamps as `int64` columns.
- **Avro stream**: the `nominal-streaming` Rust crate (`stream_to_file`) or any Apache Avro
  object-container writer using the contract schema. Batch many points per record, thousands
  rather than one.
- **Video**: remux or encode with a standard tool such as ffmpeg, keeping the camera's timing,
  and declare a start or a per-frame sidecar.
- A static or distroless runtime image may lack a shell, CA certificates or timezone data;
  confirm what the parser needs (see [registration](registration.md#choose-the-base-image)).

## Test what the data means

Exercise the parser against representative fixtures before building an image, then rehearse
the image itself with the [conformance check](contract.md#check-conformance-locally). Checks
must cover meaning, not only shape: selected expected values, channel names, units and
conversions, preserved timestamp precision, and absolute start/end bounds decoded with the
declared metadata against the fixture's known capture, including resets or malformed times.
Check declared paths, formats, timestamp fields, tag-to-column mappings, actual tag values and
consumed columns. Exercise missing or invalid parameters, malformed records, empty and
all-filtered input, and rejection counts, asserting the exit status and error code for each
failure. Row count alone is insufficient. Use existing project tests and fixtures where
practical.

In Python, `Extractor.run` takes an explicit environment, so tests need no Docker or platform
access:

```python
ctx = convert.run(
    env={"OUTPUT_DIR": str(out_dir), "RAW_FILE": str(raw_file), "THRESHOLD": "0.8"},
    exit=False,
)
manifest = ctx.build_manifest()   # the manifest document exactly as written
```

- **`env` replaces the environment rather than merging**: it must carry `OUTPUT_DIR` (an
  existing directory), every required input and every required parameter. Omitted optional
  parameters use their decorator defaults.
- `exit=False` returns the context on success and re-raises the original exception on
  failure, without termination reporting. To test mapped exits, run with the default `exit=True`
  and `termination_log_path=tmp_path / "termination.log"`, and assert on `SystemExit.code` and
  the file's JSON.
- To exercise registered-contract behavior, inject what Nominal would:
  `_NOMINAL_OUTPUT_FORMAT="MANIFEST"`, plus `_NOMINAL_INPUTS` and `_NOMINAL_PARAMETERS` in the
  shapes shown in the [contract](contract.md#metadata-variables).
- A direct `convert(ctx)` call binds arguments but neither finalizes outputs nor reports mapped
  failures; prefer `run(env=..., exit=False)`.

In other languages, unit-test the pure parsing functions natively, assert the exact emitted
`manifest.json` and termination payloads against golden files, and cover each exit status.
