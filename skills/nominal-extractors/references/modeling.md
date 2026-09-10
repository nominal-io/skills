# Modeling decisions

Start from the comparisons people need and the evidence in samples, specifications, existing
code and README. Recommend unresolved choices with concrete consequences. Reuse settled
choices; revisit them only when new evidence conflicts, explaining the conflict. The contract
belongs in parser/registration code, and its short rationale in the existing project README.

## Inputs, parameters, and compatibility

| Need | Representation | Consequence |
|---|---|---|
| File content varying per ingest: calibration table, schema, channel map | Input, supplied in `sources={"ENV_VAR": path}` | Nominal mounts it; `ctx.input("ENV_VAR")` returns its path. |
| Scalar knob varying per ingest: mode, divisor, threshold | Parameter, supplied in `arguments={"ENV_VAR": "value"}` | Values are strings; parser code must coerce and validate them. |
| Fixed resource | Code or a file copied into the image | No uploader field; changing it requires a new image. |

Content versus knob matters more than size: do not squeeze structured configuration into a
string parameter simply because it is small. Input suffixes support discovery but do not
validate file contents or enforce the uploaded suffix; validate structure in the parser.

Require values whose absence cannot safely be inferred. A required input is checked by
`add_containerized` before upload; a missing required parameter only warns at runtime startup
and fails when `ctx.param()` reads it. Read/coerce essential parameters at the top. Use
`ctx.get_param(name, default)` for an agreed default and make the parameter optional. This
reduces uploader work but can hide an accidental omission, so the default must be intentional.
Empty strings are still values and need explicit validation where invalid.

Preserve existing environment-variable names, output mode, channel names/units, timestamp
meaning and tag vocabulary unless the change is agreed. Registered display names serve people;
environment-variable names serve `sources`, `arguments`, and code. Contract changes require a
new image registration and may require caller/query changes; activation does not migrate old
data. Inspect the deployed contract in Nominal when available before changing existing work.

## Outputs and failure policy

For new work recommend `@manifest_extractor` with explicit `output_format=MANIFEST`: it
supports per-file declarations and multiple formats, even if there is only one table today.
Preserve an existing single-file contract unless migration is intended. Its decorator must
match registered `PARQUET`, `CSV`, or `AVRO_STREAM`; the registration default is `PARQUET`.
See [authoring](authoring.md) for declaration constraints.

Identify measurement channels and their units, conversions, prefixes and numeric precision.
Do not silently change a channel's physical meaning. Agree whether legitimately empty input,
all-filtered input, malformed records and missing required fields fail the job or produce an
explicitly accepted empty/partial result. Distinguish filtered from rejected records and log
aggregate counts with reasons. A green job and a positive row count do not establish useful,
correct data; check selected values and decoded times.

## Timestamps: choose from evidence

Nominal ultimately places samples on an absolute timeline. Choose an encoding that matches
the source; relative time is not a universal default.

| Source evidence | Recommendation | What must be established |
|---|---|---|
| Elapsed numeric offsets | `ts.Relative(unit=..., start=...)` for this capture | Proven units and an absolute start; inspect resets/wraparound and what event the start anchors. |
| Reliable UTC numeric timestamps | Preserve as `ts.Epoch(unit=...)` or an epoch string alias | Confirm Unix epoch and units; preserve precision, especially integer micro/nanoseconds, avoiding a lossy float conversion. |
| Absolute timestamp strings | Preserve with `ts.Iso8601()` or `ts.Custom(format=...)`, or deliberately convert | Validate exact format, timezone/offset and date completeness; ISO 8601 requires a timezone. Resolve ambiguous local time rather than guessing. |
| Unreliable or discontinuous clock | Diagnose before selecting a correction | Evidence for synchronization, reset/wraparound, jumps and drift; an agreed correction/segmentation rule or rejection policy. Subtracting the first sample does not repair clock jumps or drift. |

For a capture start, inspect validated header metadata first, then a documented filename
convention, then uploader/job metadata. This is an evidence search order, not permission to
trust any header. A parameter start adds per-upload work; use it only when the file cannot
provide a trustworthy anchor. If no start or correction can be justified, identify that
blocker rather than inventing a plausible date.

Never put a fixed per-capture start in the image default: every future upload would inherit
the same start. Supply capture-specific relative metadata per output or ingest, and choose a
compatible absolute fallback at registration. See the authoritative
[timestamp metadata contract](authoring.md#timestamp-metadata-contract) for supported types,
precedence, and the distinction between local runs and platform requirements.

## Tags: start from intended comparisons

For “compare pressure across stands and motors,” **pressure is a channel**, **time is the
timeline**, **stand is an upload dimension** if constant for the capture, and **motor is a row
dimension** if records contain several motors. Model those dimensions as tags where the output
format supports them. A channel prefix instead changes the channel name; use it for outputs
that should read as distinct measurements, not automatically for every source identifier.

- Upload dimensions come from `add_containerized(..., tags={"stand": "Stand-A"})` and are
  available to the parser as `ctx.additional_tags`.
- Row dimensions in tabular output use `tag_columns={"motor": "motor_id"}`: tag key to source
  column. The tag column is consumed, not also ingested as a measurement; copy it under another
  name only if that measurement is actually needed.
- Avro records carry tags inline. Do not assume every format supports tags: log/video methods
  have no tag-column argument. Verify format/platform behavior for required dimensions.

Preserve existing case-sensitive keys and values, especially opaque IDs. `Stand-A` and
`stand-a` are different values; lowercase/separator normalization is a compatibility decision,
not routine cleanup. Apply only agreed normalization and validate it. Choose explicit handling
for missing tags: reject, omit, or use an agreed sentinel; never invent a value silently.
Do not assume precedence when upload tags and record/column tags share a key. Prefer distinct
keys or verify the behavior required by the contract before relying on collisions.

Use stable source/comparison dimensions with manageable cardinality. Measurements, timestamps,
and constantly changing free text generally belong elsewhere. Renaming a tag does not rename
historical series.

## Example README rationale

Illustrative only; adapt to evidence and existing preferences, not as mandatory policy:

> The parser retains elapsed microseconds and uses the validated UTC start in the capture
> header. Uploaders supply the stand tag; each record supplies the motor tag. Motor IDs retain
> their original spelling and case. Records missing required IDs are rejected and counted.
> The registration script owns the image contract; parser code owns parsing defaults.

Keep that note alongside existing project usage guidance. Do not duplicate executable defaults
in a separate local JSON state file. Nominal remains the source for what is actually registered
and active.
