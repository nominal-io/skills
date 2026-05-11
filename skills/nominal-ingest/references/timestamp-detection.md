# Detecting timestamps in CSV / Parquet

Picking the wrong `--timestamp-column` or `--timestamp-type` is the #1 way to fail an ingest. This reference describes the heuristics to use and when to ask the user instead of guessing.

## Which formats use these flags?

| Format             | Needs `--timestamp-column` / `--timestamp-type`? | Notes                                                                |
|--------------------|--------------------------------------------------|----------------------------------------------------------------------|
| csv                | yes                                              | Standard case.                                                       |
| parquet            | yes                                              | Standard case.                                                       |
| journal-json       | no                                               | journald entries are timestamped natively; channel name is the only knob (`--channel`). |
| ardupilot-dataflash| no                                               | ArduPilot `.bin` carries timestamps natively.                        |
| mcap               | no                                               | MCAP messages are natively timestamped per topic. Parser handles protobuf and ROS messages; use `--include-topic`/`--exclude-topic` to scope and exclude video topics. |
| video (standalone) | no, but needs `--start <RFC3339>`                | A single timestamp for the first frame; everything after is relative to it. |
| mcap-video         | no                                               | Topic is a `foxglove.CompressedVideo` or raw H.264 stream; timestamps come from the MCAP. |

The next sections apply to csv/parquet timestamp columns. Standalone video and MCAP have format-specific notes at the end.

## What csv/parquet `nom ingest` needs

```
--timestamp-column <COLUMN>
--timestamp-type <SPEC>     # one of: iso8601 | epoch:<unit> | relative:<unit>
[--timestamp-offset <RFC3339>]   # required when type is relative:*
```

`<unit>` is one of `seconds`, `s`, `milliseconds`, `ms`, `microseconds`, `us`, `nanoseconds`, `ns`. Always normalize to the long form when writing the plan, even if the user wrote `ms`.

## Step 1: identify the column

Read the first 5 rows of CSV with `head -n 5 <file>`, or for Parquet use `duckdb -c "DESCRIBE SELECT * FROM '<file>' LIMIT 0"` if available, or `parquet-tools schema <file>`.

Score each column. Pick the highest-scoring; tie-break by leftmost.

| Signal                                                              | Score |
|---------------------------------------------------------------------|-------|
| Column name is exactly `timestamp` / `time` / `ts` / `t`            | +5    |
| Column name contains `timestamp` / `time` (e.g. `event_time`)       | +3    |
| Column name contains `date`                                         | +2    |
| Column appears first                                                | +1    |
| Values parse as ISO8601 (`2024-03-15T...`)                          | +5    |
| Values are integers/floats with magnitude consistent with epoch     | +4    |
| Values are monotonically increasing                                 | +2    |
| Values are bounded floats < 100000 (likely relative seconds)        | +2    |

If the top score is **≥ 7**, confidence is **high** — don't ask, but log the choice in the plan.
If **3–6**, confidence is **medium** — pick it but flag for confirmation.
If **< 3** or there's a tie at the top, confidence is **low** — ask the user.

## Step 2: identify the type

Look at sample values from the chosen column.

### iso8601

Anything that matches RFC3339-ish: `2024-03-15T13:42:00Z`, `2024-03-15 13:42:00.123+00:00`, `2024-03-15`.

### epoch:<unit>

Numeric values. Use the magnitude to pick the unit; the lookup is roughly:

| Magnitude of values around year 2020–2030 | Unit          |
|-------------------------------------------|---------------|
| ~1.5e9 to ~2e9                            | `seconds`     |
| ~1.5e12 to ~2e12                          | `milliseconds`|
| ~1.5e15 to ~2e15                          | `microseconds`|
| ~1.5e18 to ~2e18                          | `nanoseconds` |

If the values are in the wrong band (e.g. ~1.5e6), they aren't epoch — they're probably relative.

### relative:<unit>

Numeric values that start near 0 and increase. Pick the unit by looking at the spacing between consecutive samples and the sample rate the data is supposed to represent (usually findable in sidecar metadata or filename, e.g. `_100hz_`).

| Spacing of consecutive samples | Likely unit       |
|--------------------------------|-------------------|
| ~0.01–1.0                      | `seconds`         |
| ~10–1000                       | `milliseconds`    |
| ~10000–1000000                 | `microseconds`    |
| ~1e7–1e9                       | `nanoseconds`     |

Relative timestamps need `--timestamp-offset <RFC3339>`. Source it from, in order:

1. Sidecar metadata field: `start_time`, `started_at`, `t0`, `epoch`, etc.
2. Folder/file name with a parseable date: `2024-03-15_run_42/` → `2024-03-15T00:00:00Z`.
3. The file's mtime (`stat -f %Sm <file>` on macOS, `stat -c %y <file>` on Linux).

Always tell the user which source you used. If you fall back to mtime, mark it explicitly — mtime can be wildly off if files were copied.

## Step 3: validate

Before writing the plan:

- Compute `min(timestamp)` and `max(timestamp)`. Convert to RFC3339 using whichever type/unit you picked. Sanity-check: does the resulting date range make sense given the folder name, sidecar metadata, and file mtimes? If your computed start is in 1970, your unit is wrong.
- Check the first row vs last row — start should be before end. If reversed and the data is timestamped descending, document this and consider asking the user (Nominal expects ascending; some datasets need to be reversed before ingest, but `nom ingest` itself does not require it).

## When to bail out and ask

- Multiple plausible timestamp columns with similar scores (e.g. both `gps_time` and `system_time`).
- A column named like a timestamp but values are NaN, empty, or formatted unusually (Excel serial dates, two-column date+time, etc.).
- Mixed timezone formats in the same column.
- Timestamps that look like epoch but resolve to a date wildly inconsistent with sidecars.

In all of these, surface the question in the plan's "Things I'm unsure about" section. Don't proceed.

## Things `nom ingest` won't do for you

- **Two-column date + time**: combine them into one ISO8601 column upstream.
- **Timestamp-less files**: not ingestable as csv/parquet datasets. Tell the user.

## Standalone video `--start`

`nom ingest video <PATH> --name <N> --start <RFC3339>` requires `--start`. Source it from, in order:

1. Sidecar metadata field on the run/asset: `start_time`, `started_at`, `t0`.
2. Filename / folder name with a parseable date: `2024-03-15_cabin_cam.mp4` → `2024-03-15T00:00:00Z`.
3. Video container metadata (`ffprobe -show_format` `creation_time`), if `ffprobe` is available.
4. File mtime.

Always tell the user which source you used. Mtime is the weakest source and easy to break with a `cp -p`-less copy; flag it explicitly.

## MCAP topic timestamps

MCAP messages are timestamped at write time. There is nothing to configure at ingest. If the user reports MCAP timestamps look wrong (e.g. all zero, or huge offsets), the bug is in whatever wrote the MCAP — not something `nom ingest` can fix. Suggest they verify with `mcap info <file>`.
