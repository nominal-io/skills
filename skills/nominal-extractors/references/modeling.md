# Modeling decisions

Start from the comparisons people need and the evidence in samples, specifications, existing
code and README. Recommend unresolved choices with concrete consequences. Reuse settled
choices; revisit them only when new evidence conflicts, explaining the conflict. The contract
belongs in parser/registration code, and its short rationale in the existing project README.
These decisions are the same in every language; only their expression in code differs.

## Inputs, parameters, and compatibility

| Need | Representation | Consequence |
|---|---|---|
| File content varying per ingest: calibration table, schema, channel map | Input, supplied in `sources={"ENV_VAR": path}` | Nominal mounts it and puts its path in `ENV_VAR`; `@input` passes it as a `Path`. |
| A variable number of files, or a directory layout such as a logger session folder | One `.zip` or `.tar` input, unpacked by the extractor | Each input is a single file; the archive carries the structure. Validate its members in the parser. |
| Scalar knob varying per ingest: mode, divisor, threshold | Parameter, supplied in `arguments={"ENV_VAR": "value"}` | Arrives as a string; `@parameter(type=...)` or the direct parser must coerce and validate it. |
| Fixed resource | Code or a file copied into the image | No uploader field; changing it requires a new image. |

Content versus knob matters more than size: do not squeeze structured configuration into a
string parameter simply because it is small. Input suffixes drive discovery (which
extractors the app offers for a file) but do not validate contents or enforce the uploaded
suffix; validate structure in the parser.

Require values whose absence cannot safely be inferred. A missing required input is rejected
before the run (by `add_containerized` before upload, and by the platform). A missing required
parameter is not: the container still starts, the Python framework then fails binding before
the callback runs, and a direct implementation must check it itself. An agreed default makes
the parameter optional and reduces uploader work but can hide an accidental omission, so the
default must be intentional. Registration does not record parameter types or defaults, so
state accepted values, units and the default in the parameter description. Empty strings are
values and need explicit validation where invalid.

Preserve existing environment-variable names, output mode, channel names and units, timestamp
meaning, tag vocabulary and error codes unless the change is agreed. Registered display names
serve people; environment-variable names serve `sources`, `arguments` and code. Contract
changes require a new image registration and may require caller or query changes; activation
does not migrate old data. Inspect the deployed contract in Nominal when available before
changing existing work.

## Outputs and failure policy

For new work recommend the `MANIFEST` output format (`@extractor.manifest_extractor` in
Python): it supports per-file declarations, several formats and videos, even if there is only
one table today. Preserve an existing single-file contract unless migration is intended. See
the [contract](contract.md#output-modes) for what each mode allows.

Identify measurement channels and their units, conversions, prefixes and numeric precision.
Declare units per output in the manifest, preserving the source's symbols unless a conversion
is agreed. Do not silently change a channel's physical meaning.

Agree whether legitimately empty input, all-filtered input, malformed records and missing
required fields fail the job or produce an explicitly accepted empty or partial result.
Distinguish filtered from rejected records and log aggregate counts with reasons. A green job
and a positive row count do not establish useful, correct data; check selected values and
decoded times.

Give every failure the policy rejects a stable error code, exit status and retry decision,
because these are what uploaders and automation see:

| Failure class | Example code and status | Retryable |
|---|---|---|
| Input bytes do not decode | `MALFORMED_INPUT`, 64 | No: the same bytes fail again |
| Input decodes but yields no usable data under the policy | `NO_DATA`, 65 | No |
| Missing or invalid parameter, inputs, or output contract | `EXTRACTOR_CONTRACT`, 78 | No: fix the request or the image |
| Transient dependency, rare for pure parsers | A specific code | Yes, only if retrying the same input could succeed |

Keep configuration faults separate from data faults so an image or request problem is never
reported as bad input. Codes are part of the contract: renaming one breaks anyone who alerts
or filters on it.

## Timestamps: choose from evidence

Nominal ultimately places samples on an absolute timeline. Choose an encoding that matches
the source, preferring relative time wherever absolute time is not trustworthy.

Recommendations name the Python SDK type; in `manifest.json` each is an `epochTimeUnit`, with
a `relativeOffset` for relative time (see the [contract](contract.md#output-entries-outputs)).

| Source evidence | Recommendation | What must be established |
|---|---|---|
| Elapsed numeric offsets | `ts.Relative(unit=..., start=...)` for this capture | Proven units and an absolute start; inspect resets/wraparound and what event the start anchors. |
| Reliable UTC numeric timestamps | Preserve as `ts.Epoch(unit=...)` or an epoch string alias | Confirm Unix epoch and units; preserve precision, especially integer micro/nanoseconds, avoiding a lossy float conversion. |
| Absolute timestamp strings | Preserve with `ts.Iso8601()` or `ts.Custom(format=...)`, or deliberately convert | Validate exact format, timezone/offset and date completeness; ISO 8601 requires a timezone. Resolve ambiguous local time rather than guessing. |
| Absolute times of doubtful accuracy: unsynced clocks, intermittent GPS, rounding to the second | Elapsed time from the first sample, emitted relative with a best-estimate start | A documented start estimate, and the offset people should expect if it proves wrong. |
| Unreliable or discontinuous clock | Diagnose before selecting a correction | Evidence for synchronization, reset/wraparound, jumps and drift; an agreed correction/segmentation rule or rejection policy. Subtracting the first sample does not repair clock jumps or drift. |

Relative time is recoverable: absolute time is the elapsed value plus a start held in
metadata, so a wrong start is fixed by deleting the ingested data and re-running the extractor
on the same input with a corrected start. A wrong absolute timestamp is part of the data and
needs every value rewritten. Choosing absolute is a claim that no timestamp will ever need
altering.

For a capture start, inspect validated header metadata first, then a documented filename
convention, then uploader or job metadata. This is an evidence search order, not permission to
trust any header. If no start or correction can be justified, identify that blocker rather
than inventing a plausible date. Where the start lives decides how it is corrected, because
per-output metadata outranks the ingest request:

| Start source | Put it in | Correcting a wrong start |
|---|---|---|
| The file | That output's manifest metadata. If the header can be wrong, add an optional ISO 8601 start parameter that the extractor prefers when supplied. | Re-run with the start parameter; a request override cannot reach per-output metadata. |
| Only the uploader | No per-output metadata; the ingest request's timestamp override | Re-ingest with a corrected override. This costs per-upload work and applies to every output. |

Never put a fixed per-capture start in the image default: every future upload would inherit
the same start. Registration still requires a default even when every output declares its own
metadata; it then only reaches outputs that omit theirs and is what `_NOMINAL_TIMESTAMP_METADATA`
reports. Choose the absolute type and column that most outputs use, or would use if they
omitted per-output metadata. Use the unit the data has: declaring milliseconds for microsecond
data misplaces every sample by a factor of 1,000. See the authoritative
[timestamp metadata precedence](contract.md#timestamp-metadata-precedence) for supported types
and the distinction between local runs and platform requirements.

## Tags: start from intended comparisons

For “compare pressure across stands and motors,” **pressure is a channel**, **time is the
timeline**, **stand is an upload dimension** if constant for the capture, and **motor is a row
dimension** if records contain several motors. Model those dimensions as tags where the output
format supports them. Without a tag, two stands' `chamber_pressure` blend into one series,
which is harder to detect and undo than a failed ingest. A channel prefix instead changes the
channel name; use it for outputs that should read as distinct measurements, not automatically
for every source identifier.

- Upload dimensions come from the ingest request, `add_containerized(..., tags={"stand":
  "Stand-A"})` or the app upload, and apply to all data from the run. The container can read
  them (`ctx.additional_tags`, or `_NOMINAL_ADDITIONAL_TAGS`) but need not re-apply them.
- Row dimensions in tabular output use tag columns, `{"motor": "motor_id"}`: tag key to source
  column. The tag column is consumed, not also ingested as a measurement; copy it under another
  name only if that measurement is actually needed. Where the spelling of a tag value
  matters, such as `007` rather than `7` or `7.0`, prefer a string-typed Parquet column over
  CSV type inference, and check the resulting tag values after a representative ingest.
- Avro records carry tags inline. Do not assume every format supports tags: log and video
  outputs have no tag columns. Verify format and platform behavior for required dimensions.

Preserve existing case-sensitive keys and values, especially opaque IDs. `Stand-A` and
`stand-a` are different values, and nothing normalizes them for you: if variants occur,
agree one normalization and apply it in the extractor rather than trusting every caller.
Changing normalization for existing data splits series, so treat it as a compatibility
decision and validate it. Choose explicit handling for missing tags: reject, omit, or use an
agreed sentinel; never invent a value silently. Do not assume precedence when upload tags and
record/column tags share a key. Prefer distinct keys or verify the behavior required by the
contract before relying on collisions.

Use stable source/comparison dimensions with manageable cardinality. Measurements, timestamps,
and constantly changing free text generally belong elsewhere. Renaming a tag does not rename
historical series.

## Example README rationale

Illustrative only; adapt to evidence and existing preferences, not as mandatory policy:

> The parser retains elapsed microseconds and uses the validated UTC start in the capture
> header. Uploaders supply the stand tag; each record supplies the motor tag. Motor IDs retain
> their original spelling and case. Records missing required IDs are rejected and counted; a
> capture with none left fails as `NO_DATA`. The registration script owns the image contract;
> parser code owns parsing defaults.

Keep that note alongside existing project usage guidance. Do not duplicate executable defaults
in a separate local JSON state file. Nominal remains the source for what is actually registered
and active.
