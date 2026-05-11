# Nominal data model

A short primer on the entities you'll create. Get this right and the user's workspace stays clean across many ingests; get it wrong and they will be stuck merging or re-creating things later.

## RIDs

Every entity has an RID (resource identifier) of the form:

```
ri.<service>.<env>.<type>.<uuid>
```

For example `ri.scout.cerulean-staging.run.b3f1...`. RIDs are opaque — never parse or construct them. They come from API responses.

## Asset

A long-lived "thing" that produces data. Examples: a vehicle, a satellite, a robot, a test stand, a wind tunnel. **One asset, many runs.**

Identity is meant to be stable: `voyager-1` exists once and accumulates runs over its lifetime. Renaming is fine; merging two assets is painful.

Fields:
- `name` (required, free text)
- `description` (optional)
- `labels[]` (free-text tags, no value)
- `properties{}` (string→string map, searchable)
- `data_sources` (datasets/videos/connections attached by scope name) — **when an asset exists, this is where its data lives**, not on individual runs. Runs that link to the asset inherit these data sources for the run's time window.

See [metadata-conventions.md](metadata-conventions.md) for label vs. property guidance. Short version: **labels are ad-hoc tags** ("cracked-propeller", "needs-review"); **properties are structured key/value** users will search on for exact matches (`serial_number=SN-0042`, `firmware_version=2.3.1`, `vehicle_type=rover`, `customer=nasa`).

When in doubt: model **fewer** assets. A test rig with five sensors is one asset, not five.

## Run

A time-bounded activity on an asset (or assets, or none). Examples: a flight, a drive, a test session, a launch.

Fields:
- `title` / `name` (required)
- `start` (RFC3339, **required**) — when the run began
- `end` (RFC3339, optional) — when it ended. Optional only because of ongoing/streaming runs; **for historical data ingest you should always set it.**
- `description` (optional)
- `labels[]`, `properties{}`
- `assets[]` — zero or more asset RIDs this run is associated with. Multi-asset runs are valid (one test exercising multiple vehicles); zero-asset runs are also valid (campaign-level scratch runs).
- `data_sources` — datasets, videos, connections attached by ref name. **Only attach data sources directly to a run when the run has no asset.** Otherwise the data belongs on the asset and the run inherits it.

Runs are the unit users open in the Nominal UI. Most analysis is "show me run X". A workspace with good runs is searchable; a workspace where everything is dumped into one giant run is not.

Example labels: `cracked-propeller`, `needs-review`, `test-event-5`.
Example properties: `operator=jane.smith@nominal.io`, `test_plan_id=TP-204`, `git_sha=abc123`, `test_type=vibration`, `outcome=pass`, `phase=integration`.

## Dataset

A timeseries data resource. The on-disk format that produced it can be CSV, Parquet, MCAP (protobuf/ROS messages), journald JSON, ArduPilot DataFlash, etc. — but the dataset itself is a uniform timeseries; each channel is a signal indexed by timestamp.

**Think of a dataset as a table.** Files don't get their own datasets — they ingest *into* a dataset, adding rows. A single dataset usually spans many files ingested over time: e.g. one `dataflash` dataset on an asset accumulates the `.bin` from every flight. Each run sees the slice of the dataset that falls within its `start`/`end`. Datasets are also independent of runs: a dataset exists even if no run points at it, and the same dataset can be attached to multiple runs.

The unit of identity is **one dataset per (owner, source)**, not one dataset per file — where a *source* is a subsystem of the owner that emits data with a consistent schema (e.g. the dataflash recorder on a flight controller, an MCU telemetry CSV, an ROS topic set). Two files belong in the same dataset iff they share owner, source (= same schema), and timestamp encoding.

Created either:
- **With an ingest call** (`nom ingest csv --name <NEW>`, `nom ingest mcap --name <NEW>`, etc.). This creates the dataset and ingests the first file in one round trip.
- **Empty** via `nom dataset create --name <N>`. Then ingest into it later (`nom ingest ... --dataset <RID>`) or have a streaming writer push data into it. Empty datasets are valid and required for streaming write paths.

Subsequent files append with `--dataset <RID>` (every `nom ingest <format>` form supports it). Append doesn't take `--name` / `--label` / `--property` / `--description` — those metadata fields stay as set by the first ingest. If you need to change them later, use `nom dataset update`.

## Video

A video resource. Standalone files (`.mp4` / `.mov` / `.mkv` / `.avi` / `.ts`) ingest with `nom ingest video`; video topics inside MCAPs (`foxglove.CompressedVideo` or raw H.264) ingest with `nom ingest mcap-video --topic <T>`.

Videos accumulate the same way datasets do: one video resource per **(owner, camera/topic)**, not one per file. First file uses `--name <NAME>`; subsequent files of the same camera/topic on the same owner use `--video <RID>` to append. Each clip's `--start` places it on the timeline.

## Channel

A single signal inside a dataset. Channels carry a name, an optional description, and an optional unit. Use `nom channel set` to attach descriptions/units; it makes the data drastically more usable for whoever reads it later.

Channel names are namespaced by the dataset's ref name in a run.

## Connection

An external data source that Nominal polls or scrapes — typically Influx, Timescale. Connections are configured server-side, not by this skill.

## Where do data sources attach: asset or run?

Datasets and videos can be attached to either an asset or a run. Pick one rule and stick to it across the entire ingest — mixing produces a workspace where users can't tell where the data for any given run lives.

**The rule:**

- **If the run has an asset → attach the data to the asset.** The run is created with `--asset <RID>` and inherits the asset's data sources for its time window. A single dataset attached to an asset is visible across every run that links to that asset; you don't repeat the attachment.
- **If the run has no asset → attach the data to the run itself.** No inheritance path exists; the run is the only home for the data.

The reasoning: assets are the canonical long-lived owners of their telemetry. A vehicle's flight data belongs to the vehicle, not to one of its many test events. Attaching to the run instead orphans the data from the asset's history and forces re-attaching for every future run.

**Edge cases:**

- A run that references multiple assets: attach each dataset to the asset it came from. If you can't tell which asset owns it, ask before guessing.
- A run-specific recording (e.g. a chase-camera video shot during one specific test): still attaches to the asset under the rule. The video is timestamped — it will only surface inside the run's time window anyway.
- A dataset that genuinely spans multiple assets and isn't owned by any one of them: attach to the run, and flag the unusual shape to the user.

## Workspace

Top-level tenancy boundary inside an org. A profile pins one workspace (`workspace_rid` in the profile config). Every resource the profile creates lands in that workspace. To move a user between workspaces, configure a different profile. There are no cross-workspace actions.

## Ref names

When you attach a dataset or video to a run, you give it a ref name. Pick stable, snake_case strings derived from the data's purpose, not the filename:

- Good: `flight_telemetry`, `cabin_camera`, `imu`, `gps`, `ground_truth`
- Bad: `data_2024_03_15_v3_FINAL`, `csv_1`, `untitled`

Ref names show up in the UI and in queries. Treat them like variable names.

## Web URLs

The Rust SDK exposes `entity.nominal_url()` for assets, runs, datasets, videos. The CLI's `get` subcommands print URLs. After ingest, surface these to the user — clicking through to the new run in the UI is the fastest validation.
