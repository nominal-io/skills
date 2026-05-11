# Folder shapes the skill recognizes

A recipe book for going from a directory tree to "0..N assets, M runs, X datasets, Y videos." These shapes are illustrative — they are not regexes to match. Real test data is unstructured; you'll combine these with sidecar prose and the user's description to land on a model.

Some upfront principles:

- **Lean toward fewer entities.** A single run is the cheap default; an asset is a longer-term commitment.
- **Don't pattern-match literal words like `run_*` or `flight_*`.** Look for the *concept* of "siblings sharing a pattern with a varying suffix" — dates, sequence numbers, A/B labels, configuration variants.
- **Use names as evidence, not proof.** A folder called `voyager-1` is a hint, not a guarantee, that there's an asset to model.

## Shape 1 — flat folder, mixed files

```
campaign_2024_03_15/
  flight_telemetry.csv
  imu.parquet
  cabin_camera.mp4
  notes.txt              (free-form prose, may not exist)
```

**Default → 1 run, no asset.** Datasets and videos all attach to one run. Use the folder name (plus an extracted date) as the run name.

**Upgrade to "1 asset, no run"** if the folder is clearly a long-running dump for a named thing (sidecars or folder name reference a serial / vehicle id / unit) and there is no test-event boundary.

**Upgrade to "1 asset, 1 run"** only if both signals are present: a clearly named long-lived thing *and* a clear single test/session.

Never invent an asset name from a date or a generic word like `data`/`test`/`export`.

## Shape 2 — siblings under one parent

```
voyager-1/
  README.md              (free-form, may name the vehicle and pilot)
  Day 1/
    telemetry.csv
    imu.parquet
  Day 2/
    telemetry.csv
  Day 3/
    ...
```

Triggers when the parent has 2+ sibling subfolders that look like instances of one concept. The subfolder names will not necessarily be `run_*` — they're more often:

- Dates / date-times: `2024-03-15`, `2024-03-15_1430`
- Sequential tests: `Test 1`, `Test 2`, also `T01`, `T-01`
- Day-of-campaign: `Day 1`, `Day 2`
- Event/point labels: `Event 1`, `Event 2`, `Point A`, `Point B`, `Pt A`
- Configuration variants: `low_speed`, `high_speed`, `nominal`, `off-nominal`
- Times-of-day: `0900`, `1130`, `1430`

The signal is "siblings share a pattern with a varying suffix." Apply this whenever the names rhyme — don't try to enumerate the patterns.

→ **N runs, one per subfolder.** Whether to also create an asset depends on the parent:
- Parent name reads like a long-lived thing (`voyager-1`, `SN-0042`, `rover-blue`) → **1 asset (parent), N runs.**
- Parent name reads like a campaign or date (`fleet-test-q1`, `march-2024-tests`, `data`) → **N runs, no asset.** Apply a shared label like `campaign-fleet-test-q1` instead.

## Shape 3 — two-level tree (axis is ambiguous)

```
some-top-level/
  level-a-1/
    level-b-1/   ← data lives here
    level-b-2/
  level-a-2/
    level-b-1/
    level-b-2/
```

A two-deep tree could be `asset/run` *or* `run/asset`. Don't assume — use context:

- **Top-level looks like long-lived things, second-level looks like tests/events/dates → `asset/run`.** Each top-level folder is an asset; subfolders are its runs.
- **Top-level looks like tests/events/dates, second-level looks like long-lived things → `run/asset`.** Each top-level folder is a run; the second level represents multiple assets that participated in that run.
- **Repeated names at the second level across siblings** (every `2024-03-15`, `2024-03-16`, `2024-03-17` folder contains a `voyager-1` and a `voyager-2`) is a strong tell that the *repeated* names are the asset axis. Assets are reused across runs; runs are not reused across assets.
- **Both levels look the same** (sequential numbers at both, dates at both, no asset-like names anywhere) → ask the user.

For `run/asset`: create N runs, M assets, and attach each asset's datasets to its run with the asset's name in the ref. The same asset across multiple runs should reuse the asset RID — search before creating.

The top-level folder's basename often makes a reasonable shared label across everything (e.g. `campaign-fleet-test-q1`). Nominal has no "campaign" type — labels are how you bind a set of runs/assets together.

## Shape 4 — sidecar-driven manifest (rare)

A top-level `manifest.{yaml,json,toml}` that explicitly declares assets, runs, files, refs, and timestamps — i.e. the user has already done the modeling for you. If one exists, **trust it absolutely**, surface it in the plan, and ingest accordingly. This is rare in practice.

## Shape 5 — MCAP-heavy folder

```
ride_2024_03_15/
  drive_log.txt
  bag_001.mcap
  bag_002.mcap
  bag_003.mcap
```

Common in robotics/AV. Each `.mcap` contains many topics: most are timeseries, some are video. Treat each MCAP as **one dataset (timeseries) plus 0..N videos (one per video topic)**, all attached to the same run.

If multiple MCAPs in one folder are clearly chunks of the same recording (sequential names, contiguous timestamps), you can create the dataset and append to it, rather than creating new datasets per file.

## Shape 6 — re-ingest into existing resources

```
voyager-1/
  2024-03-20_flight_45/
    telemetry.csv
    imu.parquet
```

…where the user says "this is for asset RID `ri.scout.…asset.…`" or "extend run RID `ri.scout.…run.…`".

→ Skip creation, ingest into the named existing asset/run. Use `nom ingest csv --dataset <RID>` if also reusing a dataset; otherwise ingest as a new dataset and `nom run add-dataset` it.

## Unstructured fallback

If nothing above matches cleanly (mixed depth, no sidecars, weird names):

1. Show the tree to the user (truncated to depth 3).
2. Propose Shape 1's default: one run, no asset, all files attached.
3. Ask: "Does this look right, or should I treat subfolders as separate runs, or model an asset?"

Do not silently invent a structure when the input is ambiguous.

## Filename → ref name conventions

When attaching to a run, derive ref names from the filename (not the path):

| Filename                      | Ref name           |
|-------------------------------|--------------------|
| `flight_telemetry.csv`        | `flight_telemetry` |
| `imu.parquet`                 | `imu`              |
| `cabin-camera.mp4`            | `cabin_camera`     |
| `2024-03-15_telemetry_v3.csv` | `telemetry`        |
| `untitled1.csv`               | (ask the user)     |
| `bag_001.mcap` (timeseries)   | `bag_001` or just `mcap` if there's only one |
| `bag_001.mcap`, topic `/camera/front/image_raw` | `camera_front` |

Strip dates, version suffixes, and extension. Lowercase, snake_case. Reject names that aren't meaningful (`untitled*`, `data_1`, `csv_export`) and ask.

For MCAP videos, derive the ref from the topic, not the file: strip leading `/`, drop trailing `image_raw` / `compressed` suffixes, and snake_case. Two video topics from the same MCAP must produce different refs.

## Sidecar metadata in the wild

**Don't expect structure.** Real "metadata" is usually one of:

- A `README.md` / `README.txt` someone typed up before going home, mixing prose and bullet lists.
- A `notes.txt` with a few free-form lines: `Test: vibration sweep, 5-200 Hz, March 15. Pilot: J. Smith. Failed at 187 Hz.`
- A timestamped log line buried in a `*.log` file from the test rig.
- A folder name that encodes everything: `2024-03-15_voyager-1_vibration-sweep_run-3/`.
- An exported JSON from the test plan tool, with a custom schema and 80 keys, only 4 of which matter.
- Nothing at all.

Sometimes there's also a clean `metadata.yaml`. Don't assume it exists.

### Extraction approach

1. **Read everything plausible** in the asset and run folders: `metadata.*`, `manifest.*`, `README*`, `NOTES*`, `*.md`, `*.txt`, small `*.log` files (skip > 1 MB log files unless asked). Use `Read` directly — these are usually small.
2. **Parse opportunistically.** If a file is valid JSON/YAML/TOML, parse it. Otherwise, treat it as prose and grep for the patterns below.
3. **Look for these signals** (case-insensitive, multiple aliases each — match any):

   | Concept              | Common keys / phrases                                                                              |
   |----------------------|----------------------------------------------------------------------------------------------------|
   | Asset identity       | `asset`, `asset_name`, `vehicle`, `vehicle_id`, `unit`, `unit_id`, `serial`, `serial_number`, `sn`, `tail_number`, `bird`, `airframe` |
   | Run identity         | `name`, `title`, `run`, `run_name`, `run_id`, `test`, `test_id`, `mission`, `flight`, `flight_id`, `session` |
   | Times                | `start`, `start_time`, `started_at`, `t0`, `epoch`, `begin`, `end`, `end_time`, `ended_at`, `stop`, `duration` |
   | Operator             | `pilot`, `operator`, `tester`, `engineer`, `who`, `by`                                              |
   | Categorization       | `tags`, `labels`, `category`, `type`, `test_type`, `phase`, `outcome`, `result`, `status`, `customer`, `program`, `mission` |
   | Free-form            | `description`, `notes`, `comments`, `summary`, `purpose`                                            |
   | Hardware/firmware    | `firmware`, `firmware_version`, `fw`, `software_version`, `git_sha`, `commit`, `build`              |

4. **Date detection in prose.** Regex for `\b(20\d{2}-\d{2}-\d{2})\b` and `\b(\d{1,2}/\d{1,2}/20\d{2})\b` and the file/folder name. Confirm any inferred date with the user when it conflicts with another source.

5. **Folder name as fallback.** If you got nothing useful from sidecars, parse the folder name. Common patterns:
   - `<date>_<name>` → date + name
   - `<asset>_<run>_<n>` → asset + run number
   - `<program>__<asset>__<runtype>__<date>` (double underscores as separators)
   Don't over-fit; if parsing is ambiguous, ask.

6. **Preserve everything you can't classify.** Anything that looks like `key: value` or a JSON/YAML key the user clearly cared about should land in properties verbatim — lowercased key, snake_case, stringified value. Discarding context is worse than over-collecting it.

7. **Promote to first-class fields cautiously.** Only set `name`, `description`, `start`, `end` from a sidecar when you're confident the source is unambiguous. When unsure, surface it in the plan's "Things I'm unsure about" and let the user confirm.
