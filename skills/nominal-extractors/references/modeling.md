# Modeling decisions

The mechanics of writing an extractor are in `authoring.md`. This file covers the choices
that decide whether the resulting data is pleasant or painful to work with. They are cheap
now and expensive later: inputs and parameters are fixed at registration, and timestamps and
tags shape how every downstream query has to be written.

## Inputs vs parameters

Both arrive through the environment. The distinction is *kind*, not size:

- **Input** — a file the extractor reads. Nominal mounts it and puts its path in the declared
  environment variable. The ingest request supplies it as `sources={"ENV_VAR": path}`.
- **Parameter** — a scalar that tunes behavior, delivered as an environment-variable string.
  The ingest request supplies it as `arguments={"ENV_VAR": "value"}`.

Decide with two questions.

*Is it content, or a knob?* A calibration table, a channel map, a vendor schema sidecar is
content: make it an input, even though it feels like configuration. A sample-rate divisor, a
mode flag, a quality threshold is a knob: make it a parameter.

*Does it vary per ingest?* If it never varies, put it in the image — in the code or a
`COPY`'d file — rather than either mechanism. Every registered parameter is a field somebody
has to understand and fill in.

Two things push structured configuration toward inputs:

- Parameter values are strings with no schema. A mapping, a list, or a nested document has to
  be encoded and parsed by hand, and a malformed value fails inside your parsing code with
  whatever message you wrote.
- Inputs declare accepted suffixes (`file_suffixes=["json"]`), which is what
  `search_containerized_extractors(file_extension=...)` matches on, so they determine which
  extractors a given file is offered for. Inputs also get a real client-side required check.
  The suffixes are descriptive, not enforced locally: a `.txt` sent to an input registered
  `["json"]` still uploads.

**`required=True` is much stronger on an input than on a parameter.** A missing required
input raises in `add_containerized` before anything uploads. A missing required parameter is
not checked client-side: the runtime warns at container start, and the run fails whenever
`ctx.param()` reads it — after the upload, after the container started, mid-job. So for a
parameter the code cannot run without, either read it at the top of the function or give it a
default with `ctx.get_param(name, default)` and drop the required flag.

Name the environment variables carefully. `name` is what a person sees in the app;
`environment_variable` is what the code reads. Changing it later means a new registration
plus an update to every caller's `sources` or `arguments`.

## Absolute vs relative time

Nominal places every sample on an absolute timeline. The only question is how your output
encodes the position:

| Type | Encodes | Use when |
|---|---|---|
| `ts.Epoch(unit=...)` / `"epoch_nanoseconds"` etc. | numeric offset from the Unix epoch | the source records absolute time — the default choice |
| `ts.Relative(unit=..., start=...)` | numeric offset from an absolute `start` | the source records only elapsed time, and you can establish t0 |
| `ts.Iso8601` | absolute timestamp strings | the source carries formatted timestamps you don't want to parse |
| `ts.Custom(format=...)` | absolute strings in a `DateTimeFormatter` pattern | the same, in a non-ISO layout |

**Prefer absolute.** If the source has absolute time anywhere, per record or as a header
start plus offsets you can add, convert it in the extractor and emit `Epoch`. Absolute
output is self-describing: it survives re-registration, does not depend on metadata staying
paired with the file, and cannot be silently wrong.

Use `Relative` when the logger knows nothing but elapsed time. Then t0 has to come from
somewhere, and that choice matters: a header inside the file, the filename, a registered
parameter, or `ctx.additional_tags`. Prefer the file, which keeps it self-contained. A t0
passed as a parameter is a value someone has to get right on every upload.

**Do not register `Relative` as an image's `default_timestamp_type`.** A default is set once
and applies to every future ingest, so a fixed `start` would give every file the same t0 —
right for the first, wrong for the rest. Register an absolute default and declare `Relative`
per output in the manifest, where each file carries its own start. This is one concrete
reason to prefer manifest extractors: single-file mode has nowhere to put per-file timestamp
metadata.

Use the unit the data actually has, not a rounder one. Declaring `epoch_milliseconds` for
microsecond data does not just lose precision, it misplaces every sample by a factor of 1000.
Per-output metadata accepts numeric types only, seconds through nanoseconds; an output needing
ISO 8601 or a custom format must omit the per-output pair and inherit the job-level metadata.

## Tags

Tags separate otherwise-identical channels. A channel is identified by its name, so two test
stands both producing `chamber_pressure` collide into one series unless a tag distinguishes
them. Get this wrong and the data is not lost, it is blended — harder to notice and harder to
undo than a failed ingest.

Tags come from three places, in increasing order of specificity:

1. **The ingest request** — `dataset.add_containerized(..., tags={"vehicle": "n1234"})`.
   Applied to everything the run produces, and readable in-container as
   `ctx.additional_tags`. Use it for facts about *this upload* that the file does not know:
   which vehicle, which campaign, which operator.
2. **A tag column** — `ctx.add_tabular(path, tag_columns={"motor": "motor_id"})`. Reads the
   value per row, so one file can carry data from several sources. Use it when the
   distinguishing fact varies *within* the file.
3. **Avro records**, which carry tags inline. Hence no tag columns on `add_avro_stream`:
   there would be nothing to map.

Log outputs (`add_journal_json`) and videos (`add_video`) take neither. Log samples carry no
tags and land on a single channel, and a video is identified by its `channel`.

**A tag column is consumed, not ingested.** Naming a column in `tag_columns` applies its
values as tags to that file's rows; the column does not also become a channel. Each column is
either a measurement you can plot or a dimension you can filter by, never both. Write it out
twice, under two names, if you need both. So tagging is an authoring-time decision: per
column, you choose which of the two it becomes.

A good tag *identifies a source*, stays stable for the life of the data, and has few distinct
values: vehicle, stand, motor serial, run identifier, sensor location. A bad tag is a
measurement (that is a channel), a timestamp or anything derived from one (that is the
timeline), a value that changes constantly (it fragments the series into noise), or free text
that varies by upload — `Stand A`, `stand-a`, and `standA` become three unrelated series.

Two things to settle before the first real ingest:

- **Fix a vocabulary and enforce it in the extractor.** Tag keys and values are strings
  chosen by whoever wrote the caller, and nothing normalizes them. If the extractor sets tag
  values, normalize there — lowercase, canonical separators, validated against a known set —
  rather than trusting each uploader.
- **Choose between a tag and a channel prefix deliberately.** `channel_prefix` renames
  channels (`engine/chamber_pressure`); a tag leaves the name alone and adds a dimension. A
  prefix suits two outputs that would collide by name and should look distinct. A tag suits
  comparing the same measurement across sources, since a tag can be filtered and grouped
  while a prefix has to be matched as a string.

Both are painful to change once there is data: tag values are baked into every series
already ingested, so a renamed key or a re-spelled value doesn't migrate — it forks.
