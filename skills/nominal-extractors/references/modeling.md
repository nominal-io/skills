# Modeling decisions

The mechanics are in `authoring.md`. These are the choices that decide whether the resulting
data is pleasant or painful to work with, and they are cheap now and expensive later: inputs
and parameters are fixed at registration, and timestamps and tags shape how every downstream
query has to be written.

## Inputs vs. parameters

Both arrive through the environment. The distinction is *kind*, not size:

- **Input** — a file the extractor reads. Nominal mounts it and puts its path in the declared
  environment variable. Ingest requests supply it as `sources={"ENV_VAR": path}`.
- **Parameter** — a scalar knob, delivered as an environment-variable string. Ingest requests
  supply it as `arguments={"ENV_VAR": "value"}`.

Decide with two questions.

*Content or knob?* A calibration table, a channel map, a vendor schema sidecar is content:
make it an input, even though it feels like configuration. A sample-rate divisor, a mode
flag, a quality threshold is a knob: make it a parameter.

*Does it vary per ingest?* If it never varies, put it in the image — in the code or a
`COPY`'d file — rather than either mechanism. Every registered parameter is a field somebody
has to understand and fill in.

Two things push structured configuration toward inputs. Parameter values are strings with no
schema, so a mapping or a nested document has to be encoded and parsed by hand, and a
malformed one fails inside your parsing code. And inputs declare accepted suffixes
(`file_suffixes=["json"]`), which is what `search_containerized_extractors(file_extension=...)`
matches on — so inputs determine which extractors a file is offered for. The suffixes are
descriptive, not enforced: a `.txt` sent to an input registered `["json"]` still uploads.

**`required=True` is much stronger on an input than on a parameter.** A missing required
input raises in `add_containerized` before anything uploads. A missing required parameter is
not checked client-side at all: the runtime warns at container start, then the run fails
whenever `ctx.param()` reads it — after the upload, mid-job. So for a parameter the code
cannot run without, either read it at the top of the function or give it a default with
`ctx.get_param(name, default)` and drop the required flag.

Name the environment variables carefully. `name` is what a person sees in the app;
`environment_variable` is what the code reads. Changing it later means a new registration
plus an update to every caller's `sources` or `arguments`.

## Absolute vs. relative time

Nominal places every sample on an absolute timeline. The question is only how your output
encodes its position:

| Type | Encodes | Where it can be declared |
|---|---|---|
| `ts.Relative(unit=..., start=...)` | numeric offset from an absolute `start` | per output, or per ingest |
| `ts.Epoch(unit=...)` / `"epoch_nanoseconds"` etc. | numeric offset from the Unix epoch | per output, per ingest, or the image default |
| `ts.Iso8601` | absolute timestamp strings | per ingest, or the image default |
| `ts.Custom(format=...)` | absolute strings in a `DateTimeFormatter` pattern | per ingest, or the image default |

**Default to relative, and treat absolute as a claim you can back.** With relative
timestamps, absolute time is `(elapsed in the file) + (t0 in metadata)`, so a wrong t0 is a
metadata error: delete the file and re-ingest the same bytes with a corrected `start`. With
absolute timestamps the times *are* the data, so the only fix is to download the file,
rewrite every value, and upload it again. Relative also asks less of the source — how far
into the recording is this sample, which the logger measures off its own clock — where
absolute asks every sample to be right in wall-clock time, which depends on GPS lock, NTP
sync, and drift.

So:

- the source records only elapsed time → emit relative, with a t0 you can establish;
- the source records absolute time you *cannot* vouch for (unsynced machines, intermittent
  GPS, timestamps rounded to the second, occasional jumps) → convert to elapsed-from-first-
  sample and emit relative with a best-estimate t0;
- the source records absolute time you can vouch for → emit `Epoch` (or pass the strings
  through as `Iso8601`/`Custom` via job-level metadata). Nothing is left for an uploader to
  supply, which is the payoff.

Where t0 comes from matters as much as the choice. Prefer a header inside the file, which
keeps it self-contained; then the filename; then the ingest request. A t0 passed as a
parameter is a value someone has to get right on every upload.

**Never register `Relative` as an image's `default_timestamp_type`.** A default is set once
and applies to every future ingest, so a fixed `start` gives every file the same t0 — right
for the first, wrong for the rest. Register an absolute default as the fallback and supply
`Relative` per output in the manifest (each file carrying its own start) or per ingest on
`add_containerized`.

Use the unit the data actually has. Declaring `epoch_milliseconds` for microsecond data does
not merely lose precision, it misplaces every sample by a factor of 1000. Per-output metadata
accepts numeric types only, seconds through nanoseconds; an output needing ISO 8601 or a
custom format must omit the per-output pair and inherit the job-level metadata.

## Tags

Tags separate otherwise-identical channels. A channel is identified by its name, so two test
stands both producing `chamber_pressure` collide into one series unless a tag distinguishes
them. Get this wrong and the data is not lost, it is blended — harder to notice and harder to
undo than a failed ingest.

Tags reach the data three ways, in increasing specificity:

1. **The ingest request** — `add_containerized(..., tags={"vehicle": "n1234"})`. Applied to
   everything the run produces, and readable in-container as `ctx.additional_tags`. Use it for
   facts about *this upload* that the file doesn't carry: which vehicle, campaign, operator.
2. **A tag column** — `ctx.add_tabular(path, tag_columns={"motor": "motor_id"})`. Read per
   row, so one file can carry data from several sources. Use it when the distinguishing fact
   varies *within* the file.
3. **Avro records**, which carry tags inline — hence no tag columns on `add_avro_stream`.

Log outputs (`add_journal_json`) and videos (`add_video`) take neither: log samples carry no
tags and land on one channel, and a video is identified by its `channel`.

**A tag column is consumed, not ingested.** Naming a column in `tag_columns` applies its
values as tags to that file's rows; the column does not also become a channel. Each column is
either a measurement you can plot or a dimension you can filter by, never both — write it out
twice, under two names, if you need both.

A good tag *identifies a source*, stays stable for the life of the data, and has few distinct
values: vehicle, stand, motor serial, run identifier, sensor location. A bad tag is a
measurement (that's a channel), a timestamp or anything derived from one (that's the
timeline), a value that changes constantly (it fragments the series into noise), or free text
that varies by upload — `Stand A`, `stand-a`, and `standA` become three unrelated series.

Two things to settle before the first real ingest:

- **Fix a vocabulary and enforce it in the extractor.** Tag keys and values are strings
  chosen by whoever wrote the caller, and nothing normalizes them. If the extractor sets tag
  values, normalize there — lowercase, canonical separators, validated against a known set —
  rather than trusting each uploader.
- **Choose between a tag and a channel prefix deliberately.** `channel_prefix` renames
  channels (`engine/chamber_pressure`); a tag leaves the name alone and adds a dimension. A
  prefix suits two outputs that would collide by name and should read as distinct. A tag suits
  comparing the same measurement across sources, since tags can be filtered and grouped while
  a prefix has to be matched as a string.

Both are painful to change once data exists: tag values are baked into every series already
ingested, so a renamed key or a re-spelled value doesn't migrate — it forks.
