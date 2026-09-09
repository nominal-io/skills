---
name: nominal-ingest
description: Ingest a folder of test/campaign data into Nominal. Use when the user points you at a directory of CSV/Parquet/video files and wants assets, runs, and datasets created with sensible labels and properties. Authenticates the `nomctl` CLI, infers folder structure, proposes a plan, then executes it.
---

# Nominal ingest

Help a user move data from disk into Nominal. The user will point you at a folder; you walk it, infer what should be modeled as assets vs. runs vs. datasets, propose a plan, and execute it via the `nomctl` CLI.

**Always plan first, execute second.** Never create resources or ingest data before showing the user a written plan and getting approval.

## Available tools and files

Resolve bundled references relative to this skill's installed directory, using the host's
skill-resource interface or provided filesystem location. Do not assume the current working
directory contains the skill files.

Before running the workflow, check whether this environment can access the source folder and
run `nomctl`. A path on the user's machine may not exist in a cloud session. If a capability
is missing, use supplied file listings or format details to prepare a provisional ingestion
plan and commands for the user's machine; identify what must be inspected before execution.
Do not invent a folder inventory or claim authentication, uploads, or resource creation
succeeded without observing them. Existing profiles can be used without displaying secrets;
do not ask the user to paste tokens into chat. The approval boundary above still applies.

## Concepts you must know before doing anything

Read [references/data-model.md](references/data-model.md) once before your first plan. Asset, Run, Dataset, Video, Channel, Connection — these terms map to specific things in Nominal and the wrong choice produces a messy workspace that is hard to clean up.

The short version:

- **Asset** = the long-lived thing that produces data (vehicle, satellite, robot, test stand). Stable identity across many runs.
- **Run** = a time-bounded activity, optionally tied to one or more assets (a flight, a drive, a test session). Has a `start` and an `end` — for historical data ingest (this skill's main case) **always set both**; the end-is-optional case is for ongoing/streaming runs only. Datasets are attached to runs under named refs.
- **Dataset / Video** = the actual file you ingest. Lives independently and gets attached to runs/assets by ref name.
- **Channel** = one signal column inside a dataset. Channels can have descriptions and units.

## Workflow

### 1. Verify auth

When `nomctl` is available, list existing profiles and pick one before executing ingestion:
For a planning-only fallback, record authentication as unverified and continue with the
information available.

```sh
nomctl config profile list
nomctl --profile <PROFILE> user who-am-i
```

If `who-am-i` succeeds, you're done. Skip to step 2.

#### If the user has no profile yet

**Don't ask the user to paste a token into chat.** Tokens are sensitive and chat transcripts get saved. Instead, ask the user to run `nomctl config profile add` themselves, in their own terminal, then come back. Send them this template and ask them to fill in the four bracketed values:

```sh
nomctl config profile add <NAME> \
  --url https://api.<tenant-host> \
  --token <TOKEN> \
  --workspace-rid <WORKSPACE_RID>
```

Then describe each blank — **do not invent values**:

- `<NAME>`: a short profile name the user picks (e.g. `prod`, `staging`, `acme`). They'll pass it as `--profile <NAME>` from here on.
- `<tenant-host>`: ask the user — this is environment-specific and you cannot guess it. The subdomain is always `api`; the rest depends on deployment. Real examples:
  - SaaS gov tenant: `https://api.gov.nominal.io`
  - SaaS gov staging: `https://api-staging.gov.nominal.io`
  - Self-hosted: `https://api.nominal.<customer-domain>` (e.g. `https://api.nominal.acme.com`)
- `<TOKEN>`: from the Nominal web UI under user settings → API keys, or a JWT for SSO users. **Stays in the user's terminal — they paste it into their own shell, not into chat.**
- `<WORKSPACE_RID>`: required. Ask the user which workspace they want resources to land in — they can get the RID from the web UI workspace settings.

Once they confirm the profile is created, verify it from your end:

```sh
nomctl --profile <NAME> user who-am-i
```

#### Passing the profile to every `nomctl` call

Shell state may not persist between tool calls. Pass the profile on every `nomctl`
invocation instead of relying on an earlier `export NOMINAL_PROFILE=...`.

**Preferred: env-var prefix on the same line.**

```sh
NOMINAL_PROFILE=<NAME> nomctl <SUBCOMMAND> ...
```

This sets `NOMINAL_PROFILE` for that single command in a way that survives shell parsing cleanly. It's the standard Unix idiom and works in any fresh shell. Use this everywhere unless you need to override the profile for one specific call (e.g. comparing two tenants).

**Alternative: inline `--profile` flag.** Same effect, but the flag must go **before** the subcommand: `nomctl --profile <NAME> <SUBCOMMAND> ...`. `nomctl <SUBCOMMAND> --profile <NAME>` will fail with `unexpected argument`. `--profile` overrides `NOMINAL_PROFILE` if both are set.

**Do not** pack flags into a single string variable and expand it bare (`P="--profile foo"; nomctl $P ...`). Shell word-splitting is fragile and intermittently treats the whole thing as one argument.

### 2. Walk the folder

Read [references/folder-patterns.md](references/folder-patterns.md) for the recognized shapes. Use `Bash` (`find`, `ls`, `head`) and `Read` to:

- Map the directory tree (one or two levels typically). Spot subfolders that look like runs (`run_*`, `2024-03-15_*`, `flight_42`, etc.) and subfolders that look like assets (asset name, vehicle ID, serial number).
- Find any sidecar metadata. **Don't expect a schema.** Read everything plausibly informative: `metadata.{json,yaml,yml,toml}`, `manifest.*`, `README*`, `NOTES*`, `*.md`, `*.txt`, log files in the root, even unstructured prose. Loose name/date/vehicle hints are common; rigid manifests are rare. Use [references/folder-patterns.md](references/folder-patterns.md) for how to extract value from messy metadata.
- Classify files (one row, one ingest command):

  | Extension(s)                               | Treat as                                                             |
  | ------------------------------------------ | -------------------------------------------------------------------- |
  | `*.csv`                                    | dataset → `nomctl ingest csv`                                           |
  | `*.parquet` (single)                       | dataset → `nomctl ingest parquet`                                       |
  | `*.tar`, `*.tar.gz`, `*.zip` of parquet    | dataset → `nomctl ingest parquet --archive`                             |
  | `*.mcap`                                   | **see MCAP section below** — one timeseries dataset + 0..N videos    |
  | `*.jsonl`, `*.jsonl.gz` (journald-style)   | dataset → `nomctl ingest journal-json`                                  |
  | ArduPilot `.bin`                           | dataset → `nomctl ingest ardupilot-dataflash`                           |
  | `*.mp4`, `*.mkv`, `*.avi`, `*.ts`, `*.mov` | video → `nomctl ingest video --start <RFC3339>` (start is **required**) |
  | anything else                              | ignore unless the user asks                                          |

  Ignore lock files, `.DS_Store`, hidden files, and obvious build artifacts.

- For tabular files (csv/parquet/journal-json/ardupilot), peek at the header (CSV: `head -n 5`; Parquet: `duckdb -c "DESCRIBE SELECT * FROM '<f>' LIMIT 0"` if available). Capture column names. Apply [references/timestamp-detection.md](references/timestamp-detection.md) to pick `--timestamp-column` and `--timestamp-type`. MCAP and standalone video do **not** use those flags — see below.

#### MCAP files

MCAP is common in robotics/AV/drone work and is unusual because **one file produces a timeseries dataset plus 0..N videos** (one per video topic):

- **Timeseries topics** → one dataset, ingested with `nomctl ingest mcap`. Nominal's MCAP parser supports **protobuf** and **ROS** messages; topics in any other schema will be skipped (use `--ignore-invalid-topics`). Topic timestamps are native; no `--timestamp-column`/`--timestamp-type`.
- **Video topics** → one **separate** video resource per topic, each ingested with `nomctl ingest mcap-video --topic <TOPIC>`. Nominal supports exactly two video encodings inside MCAP: **`foxglove.CompressedVideo`** messages, or raw **H.264** byte-stream messages. Anything else is not a video topic — don't try.
- **Video topics must be excluded from the timeseries ingest.** They will fail or pollute the dataset. Always pass `--exclude-topic <T>` for every video topic identified.

Workflow for an MCAP:

1. Inspect topics. If `mcap` (the CLI) is on PATH, use `mcap info <file>`; otherwise ask the user. Capture each topic's schema name.
2. Classify each topic:
   - **Video** if schema is exactly `foxglove.CompressedVideo`, or the topic carries a raw H.264 stream. (Topic name hints like `image`/`camera` are not enough — confirm via schema.)
   - **Timeseries** if schema is a protobuf or ROS message. The mcap parser will handle these.
   - **Skip** otherwise.
3. Plan one `nomctl ingest mcap` per file. Pass `--exclude-topic <T>` for every video topic. Use `--include-topic` if the user wants to scope further. Add `--ignore-invalid-topics` if there are topics in unsupported schemas you want the parser to skip rather than fail on.
4. Plan one `nomctl ingest mcap-video --topic <T>` per supported video topic. Each yields a distinct video resource — name them `<file_basename>__<topic>` after stripping leading slashes (e.g. `front_camera__camera_front`).
5. Attach all of them to the run with separate `nomctl run add-dataset` / `nomctl run add-video` calls.

Show the topic classification (video / timeseries / skipped) in the plan so the user can override before you ingest.

Don't re-scan the world. Cap your walk at depth 3 by default; ask if the tree is deeper or has tens of thousands of files.

#### Missing inspection tools

The walk often wants tools that aren't always installed: `mcap` (CLI), `duckdb` (Parquet schema), `openpyxl` / a Python interpreter (xlsx sidecars), `ffprobe` (video metadata). If a tool you'd use is missing:

1. Check what _is_ available: `which pipx uvx pip3 brew`.
2. **Ask the user before installing anything.** Show them the exact command you'd run (e.g. `uvx --from openpyxl python -c …`, `brew install duckdb`, `pipx install mcap`) and the reason you need it. Don't install silently — the user may already have a preferred install path, or may prefer you just skip the inspection and ask them for the info instead.
3. If they decline, fall back to asking the user for the metadata you would have inspected. Don't guess.

### 3. Decide what to model as what

Real test/campaign data rarely fits a clean schema. The shapes below are starting points, not rules — use sidecar prose, file naming, and the user's own description to override. Lean toward **fewer entities**: creating an asset commits the user to a name they'll see for a long time; creating a run is cheap.

#### Default: one run, no asset

For a small, one-off folder dump, attach all datasets/videos to a single run named after the folder (plus any date you can extract). Don't create an asset unless you have positive evidence one is appropriate. This is almost always right for a "here's the data from yesterday's test" folder.

#### When to create an asset

Create an asset only when there's a signal pointing at a long-lived, identifiable _thing_:

- A serial number, vehicle id, callsign, robot name, tail number, or unit id appears in sidecars or the folder name.
- The user names an asset directly ("this is for Voyager-1").
- The structure clearly implies one (multiple tests/events/days under a single named unit — see multi-run below).

If the only "asset" candidate is the folder basename and that basename is a date or a generic word like `data`, `test`, or `export`, **do not** create an asset.

When in doubt: skip the asset, just make a run. You can always go back and add an asset later, but a workspace cluttered with one-off "asset: 2024-03-15-data" entries is hard to clean up.

#### Asset, no run

When the folder is clearly the steady-state output of a long-lived thing (named asset signal present) and there is **no** apparent test/event boundary — e.g. continuous logger dumps, fleet telemetry — attach datasets directly to the asset and skip the run.

#### Multi-run shapes

When subfolders look like "one of many similar things." Subfolder names will rarely look like `run_*` — real data uses anything that parses as a sequence:

- Dates / date-times: `2024-03-15/`, `2024-03-15_1430/`
- Sequential tests: `Test 1`, `Test 2`, `Test 3`, also written `T01`, `T-01`
- Day-of-campaign: `Day 1`, `Day 2`
- Event / point labels: `Event 1`, `Event 2`, `Point A`, `Point B`, `Pt A`
- Configuration variants: `low_speed/`, `high_speed/`, `nominal/`, `off-nominal/`
- Times-of-day on a single test day: `0900`, `1130`, `1430`

The signal is "siblings share a pattern with a varying suffix." Don't grep for specific words.

→ When this shape applies _and_ the parent folder names a long-lived thing → 1 asset, N runs.
→ When this shape applies _and_ the parent is just a date/campaign label with no asset signal → N runs, no asset.

#### Two-level trees: don't assume the axis

A two-deep tree could be `asset/run` (one asset, several tests under it; another asset, several tests under it) **or** `run/asset` (a single test exercising several assets). Use context:

- **Top-level looks like long-lived things, second-level looks like tests/events/dates → `asset/run`.** Each top-level folder is an asset.
- **Top-level looks like tests/events/dates, second-level looks like long-lived things → `run/asset`.** Each top-level folder is a run, and each run involved multiple assets sharing data.
- **Repeated names at the second level** across siblings (e.g. every `2024-03-15`, `2024-03-16`, `2024-03-17` folder contains a `voyager-1` and `voyager-2`) is a strong signal that the repeated names are the asset axis — assets are reused across runs; runs are not reused across assets.
- **Both levels look the same** (sequential numbers at both, dates at both, no asset-like names anywhere) → ask the user. Don't pick.

#### Sidecar context wins

Whatever structural inference you made, override it with what the sidecars say. Sidecars rarely arrive as `metadata.yaml: asset: voyager-1` — they're more often notes saying _"Vibration sweep on Voyager-1, March 15, by Jane"_, or a folder named `voyager-1__2024-03-15_vibration`. Whatever you can extract from prose about a vehicle/serial/test/operator, use it. See [references/folder-patterns.md](references/folder-patterns.md) for the alias lists.

If the user already has matching assets in Nominal, prefer reuse. Use `nomctl asset search` (substring/label/property filters) when you have a hint to narrow on, or `nomctl asset list` when the user wants to eyeball everything. Same for runs (`nomctl run search` / `nomctl run list`). When the user confirms a match, use that RID instead of creating a new resource.

### 4. Bucket files, then pick timestamps and metadata

#### Bucket files into datasets first

**Think of a dataset as a table.** You don't create a new table for every file — files from the same **source** on the same asset share a table so you can query across them. One dataset per (owner, source), not one per file. Subsequent files append into the existing table, accumulating rows; Nominal slices the table by each run's `start`/`end`.

A "source" here means a subsystem of the asset that produces data with a consistent schema — e.g. the `dataflash` recorder on a flight controller, the `mcu_telemetry` CSV from the avionics MCU, a specific camera/topic on a robot. Two files share a source iff they share a schema (same columns / channel set) and a timestamp encoding.

Bucket files into datasets by (owning-asset, source) **before** picking timestamps:

- Same file extension + same column/channel schema + same producing subsystem → same dataset. Example: every flight folder for `WNG-001` has a `*.bin` dataflash → one `dataflash` dataset on `WNG-001` that all `.bin` files ingest into.
- For MCAPs, the source is identified by the (set of) topics carried by that recording. If every flight produces the same MCAP topic set on the same robot → one MCAP dataset on that asset.
- For videos: one video resource per (asset, camera/topic) — each camera/topic is its own source. Subsequent flights append via `--video <RID>`.
- If two files claim to be the same source but have different column schemas or different timestamp encodings → **they are not the same source.** Flag it and split.

When the asset is shared across many flights, the dataset name should describe the source (and optionally the asset), not the flight. Use stable scope names per asset: `dataflash`, `mcu_telemetry`, `gimbal`, `flight_video`, etc. The scope name appears in `nomctl asset add-dataset <ASSET_RID> <SCOPE> <DATASET_RID>`. Reuse the same scope name across flights — that's the whole point.

If no asset is involved (run-only ingest), it's still one dataset per source _for that run_, not one per file — unless the files genuinely come from different sources.

#### Then pick timestamps

For each tabular file:

- `--timestamp-column` and `--timestamp-type` per [references/timestamp-detection.md](references/timestamp-detection.md). If you have to guess, mark the guess in the plan and flag it for confirmation.
- If timestamps are `relative:*`, you also need `--timestamp-offset <RFC3339>`. Try in order: sidecar metadata → folder-name date → file mtime. Flag anything you fall back to.
- **All files going into the same dataset must share the same `--timestamp-column` and `--timestamp-type`.** If they don't, they're not from the same source — split them.

For runs:

- `--start` is required. In order: sidecar metadata `start_time` → minimum timestamp across the run's datasets (read from data) → folder-name date at midnight UTC → file mtime. Always tell the user where you got it.
- `--end` should always be set for historical ingest. Source order: sidecar metadata `end_time` → max timestamp across the run's datasets → folder-name end-date if present → `start + sidecar duration`. The CLI accepts an end-less run, but those are reserved for ongoing/streaming runs and aren't appropriate here. If you genuinely cannot derive an end, surface it in the plan's "Things I'm unsure about" and ask the user.

For labels and properties (apply consistently across the resources you create — see [references/metadata-conventions.md](references/metadata-conventions.md)):

- **Labels** (ad-hoc tags with no key): `ingested-by-skill`, plus genuinely unstructured tags from sidecar prose — observations, statuses, free-form notes (e.g. `cracked-propeller`, `needs-review`, `re-run-pending`). **Don't write `vibration-test`, `customer-nasa`, or `phase-integration` as labels** — those have implicit keys and belong in properties.
- **Properties** (key/value, searchable): describe the **event and the on-disk source**, not the contents of the file.
  - `ingest_session_id`: a UUID you generate once per skill run and stamp on every resource. Don't add `ingested_at` / `ingested_by` — the platform records creator and creation time itself.
  - Anything from sidecar metadata that describes the test/run/asset (operator, vehicle id, firmware version, test plan id, customer, program, …) — lowercased keys, snake_case.
  - Do not synthesize properties from inside the file (channel names, topic lists, schema info, row counts, file size). That's data, not metadata.

### 5. Write the plan, get approval

Output a single markdown plan to chat that includes:

```
## Ingest plan for <folder>

Profile: <name> · Workspace: <rid or None>

### Assets to create (N)
- <name> — labels: [...], properties: {...}

### Assets to reuse (M)
- <rid> (<name>) — confirmed by user

### Runs to create (K)
- <name> on assets [<name>...]   (zero or more)
  - start: <RFC3339>  [source: sidecar | data-min | folder-date | mtime]
  - end:   <RFC3339>  [source: sidecar | data-max | folder-date | start+duration]
  - labels: [...]
  - properties: {...}
  - data sources attach to: <ASSET name(s)>  ← when this run has any asset
                            <this run>       ← only when run has no asset

### Datasets (X)
One dataset per (owner, source). All listed files ingest into the **same** dataset (= same table), in order.

- owner: <ASSET name> | <RUN name>            ← asset preferred when an asset exists
  scope name: <stable_snake_case>             ← e.g. `dataflash`, `mcu_telemetry`
  dataset name: <name>                        ← if creating new
  reuse existing dataset RID: <rid or none>   ← if found via search
  format: csv | parquet | mcap | journal-json | ardupilot-dataflash
  timestamp-column: <col>  [confidence: high | medium | low]   ← csv / parquet only
  timestamp-type:   <spec>                                     ← csv / parquet only
  timestamp-offset: <RFC3339 or n/a>                           ← only when type is relative:*
  mcap topics:      include=[…] exclude=[…video topics…]       ← mcap only
  files (in ingest order):
    - <file 1>   ← first file: creates the dataset (--name)
    - <file 2>   ← subsequent: appends (--dataset <RID>)
    - ...

### Videos (Y)
One video resource per (owner, camera/topic). All listed files ingest into the **same** video.

- owner: <ASSET name> | <RUN name>
  scope name: <stable_snake_case>             ← e.g. `flight_camera`, `cabin_camera`
  video name: <name>                          ← if creating new
  reuse existing video RID: <rid or none>
  source: standalone | mcap-topic
  mcap topic: <topic>                         ← mcap-video only
  files (in ingest order):
    - <file 1>  start: <RFC3339> [source: …]  ← standalone video only; required per file
    - <file 2>  start: <RFC3339>
    - ...

### Things I'm unsure about
- <...>  ← user must answer or override before I proceed
```

Wait for an explicit "go" from the user. If they push back on anything, revise the plan and show it again. Don't execute partially.

### 6. Execute

In this order:

1. **Create asset(s)** (if not reusing): `nomctl asset create --name ... --label ... --property K V ...`. Capture the returned RID.
2. **Create run(s)**: `nomctl run create --name ... --start ... --end ... [--asset <ASSET_RID>...] --label ... --property K V ...`. `--asset` is repeatable. Capture the run RID. Do **not** attach data sources to runs here — runs that link to an asset inherit the asset's data sources for the run's time window. See step 4 for where data sources go.
3. **For each (owner, source) dataset in the plan**, do this:

   a. **First file** — create the dataset and attach to its owner. The first ingest of a (owner, source) bucket uses `--name`; capture the resulting dataset RID. Then attach once.

   ```sh
   # Tabular — first file in the bucket
   nomctl ingest csv <FILE_1> --name <DATASET_NAME> \
     --timestamp-column <COL> --timestamp-type <SPEC> [--timestamp-offset <RFC3339>] \
     --label ingested-by-skill ...
   # → captures DATASET_RID from output line `Dataset RID: ri.…`

   # MCAP — first file. Always exclude video topics.
   nomctl ingest mcap <FILE_1> --name <DATASET_NAME> \
     [--include-topic <T>]... --exclude-topic <VIDEO_T>... [--ignore-invalid-topics] ...

   # Attach the new dataset to its owner (once per dataset, not once per file).
   # Use the asset when an asset exists; otherwise the run.
   nomctl asset add-dataset <ASSET_RID> <SCOPE_NAME> <DATASET_RID>
   nomctl run   add-dataset <RUN_RID>   <SCOPE_NAME> <DATASET_RID>   # only when no asset
   ```

   b. **Subsequent files in the same bucket** — append to the existing dataset using `--dataset <RID>`. No re-attach.

   ```sh
   nomctl ingest csv     <FILE_2> --dataset <DATASET_RID> \
     --timestamp-column <COL> --timestamp-type <SPEC> ...
   nomctl ingest mcap    <FILE_2> --dataset <DATASET_RID> --exclude-topic <VIDEO_T>... ...
   nomctl ingest parquet <FILE_2> --dataset <DATASET_RID> --timestamp-column <COL> --timestamp-type <SPEC> ...
   ```

   All ingest forms (`csv`, `parquet`, `mcap`, `journal-json`, `ardupilot-dataflash`) support `--dataset <RID>` to append to an existing dataset. Append-time flags like `--label` / `--property` / `--description` are only allowed with `--name`; metadata stays as set by the first ingest.

4. **For each (owner, camera/topic) video in the plan**, the same pattern with `--video <RID>`:

   ```sh
   # First file
   nomctl ingest video      <FILE_1> --name <VIDEO_NAME> --start <RFC3339> ...
   nomctl ingest mcap-video <FILE_1> --topic <TOPIC> --name <VIDEO_NAME> ...
   # → captures VIDEO_RID
   nomctl asset add-video <ASSET_RID> <SCOPE_NAME> <VIDEO_RID>   # or `nomctl run add-video` if no asset

   # Subsequent files append to the same video
   nomctl ingest video      <FILE_2> --video <VIDEO_RID> --start <RFC3339> ...
   nomctl ingest mcap-video <FILE_2> --video <VIDEO_RID> --topic <TOPIC> ...
   ```

5. **Attach rule (recap).** When an asset exists for a run, all data sources attach to the **asset**, and the run links via `--asset <RID>`. Only attach to a run directly when no asset is involved. Never mix — for any given run, its data sources live on _either_ its asset(s) _or_ the run itself, but not both. If a run has multiple assets and a dataset clearly came from one of them (e.g. per-asset subfolders), attach to that specific asset; ask before guessing.

   Pick stable, snake_case scope/ref names derived from the source, not the filename. Use the **same** scope name across runs/flights for the same source on the same asset — that's how the data accumulates under one name in the UI. For MCAP video resources, derive from the topic (e.g. topic `/camera/front/image_raw` → `camera_front`).

6. After ingests finish, optionally call `nomctl channel set` to attach descriptions/units if the user provided a channel dictionary in sidecar metadata.

#### Parallelism and failure cost

Mass-parallel ingest is expensive to fail: ingesting a dozen files concurrently and then discovering your command template is wrong wastes upload time and pollutes the workspace with orphans.

- **Within one dataset bucket, ingest serially.** The first file (`--name`) must finish and return its RID before subsequent files (`--dataset <RID>`) can reference it. Don't parallelize files within a bucket.
- **Across buckets, you can parallelize** — different datasets are independent. Cap concurrency at ~5–10 parallel ingests across buckets. More doesn't help: the bottleneck is upload bandwidth, and the failure blast radius scales with concurrency.
- **Always run one full bucket end-to-end first** (first-file ingest → attach → one append) before fanning out the rest. This validates your command template and RID parsing on a small number of resources before you commit a dozen.
- If any of the first 1–2 attaches fails — stop. Re-read the actual output before retrying. Do not loop-retry a failing command template against more inputs.

#### Parsing RIDs from CLI output

The CLI prints resource-typed RID lines, not bare `RID:`. Grep for the exact prefix:

```sh
# After: nomctl ingest csv ...
nomctl ingest csv <PATH> --name <N> ... | tee /tmp/ingest.out
DATASET_RID=$(grep -oE 'Dataset RID: ri\.[^ ]+' /tmp/ingest.out | awk '{print $3}')

# After: nomctl ingest video ... or nomctl ingest mcap-video ...
VIDEO_RID=$(grep -oE 'Video RID: ri\.[^ ]+' /tmp/ingest.out | awk '{print $3}')

# After: nomctl asset create / nomctl run create
RID=$(grep -oE 'ri\.[a-z0-9-]+\.[a-z0-9-]+\.[a-z0-9-]+\.[a-f0-9-]+' /tmp/create.out | head -1)
```

If you got an empty RID once, fix the parser before reusing it across N more ingests. An empty `<DATASET_RID>` will produce `RID conversion error: invalid RID '': ParseError` on every subsequent attach.

### 7. Verify and report

After execution:

- `nomctl run get <RUN_RID>` for each run, confirm the data sources are attached.
- For datasets, list the channels via `nomctl channel list <DATASET_RID>` and spot-check a few names.
- Print a final summary with web URLs (the SDK exposes `nominal_url()`; the CLI prints links on `get` for assets/runs/datasets).

If anything failed mid-execution, do not auto-rollback. Report what was created with RIDs so the user can clean up or retry, and stop.

## Common pitfalls

- **Wrong timestamp unit**: ingesting `epoch:milliseconds` data as `epoch:seconds` produces datasets dated in 1970. Always confirm if confidence is anything below "high".
- **Duplicate runs**: re-running this skill on the same folder will create duplicate runs unless you list and check first. Always offer to reuse before creating.
- **Mass-ingest in one transaction**: there isn't one. Each `nomctl ingest` call is independent. If you fail halfway, you have orphans. Run the first ingest sequentially to validate the command and the RID-parsing, then fan out.
- **Attaching data to runs when an asset exists**: if the run is linked to an asset, the dataset/video belongs on the _asset_, not the run. The run inherits it. Mixing the two patterns within one ingest leaves the user unable to find their data.
- **One dataset per file (instead of per source)**: ingesting `WNG-001/flight1/dataflash.bin` and `WNG-001/flight2/dataflash.bin` as two separate datasets is wrong. A dataset is a table; same asset + same source (same schema) = same table, and the second file appends with `--dataset <RID>`. The dataset accumulates across flights; Nominal slices it by each run's `start`/`end`. Same rule for videos with `--video <RID>`.
- **Profile delivery**: prefer `NOMINAL_PROFILE=<NAME> nomctl <SUBCOMMAND> ...` (env-var prefix is safe in any fresh shell). If you use the flag instead, it goes **before** the subcommand: `nomctl --profile <NAME> <SUBCOMMAND>` — never `nomctl <SUBCOMMAND> --profile <NAME>`.
- **Shell variable expansion for flags**: don't pack multi-word flags into one string variable (`P="--profile foo"; nomctl $P …`). Use the env-var prefix or inline the flag.
- **Workspace mismatch**: if the user's profile has a `workspace_rid` set, every resource you create lands in that workspace. If they want a different workspace, they need a different profile. Don't try to override per-call.
- **Don't paste tokens into chat**. Have the user run `nomctl config profile add` themselves; verify with `nomctl user who-am-i`.
- **Never call `nomctl api` or `nomctl endpoint list`.** They expose raw REST/gRPC endpoints (archive, delete, configuration changes) with no guard-rails and can cause irreversible, cross-tenant damage. If the task seems to need an endpoint with no dedicated `nomctl <subcommand>` for it, stop and ask the user — they will run it themselves if appropriate.

## When this skill does not fit

- **Streaming / live data** (Nominal connections, gRPC streaming ingest): out of scope. Point the user at the streaming docs.
- **Already-modeled data needing a re-ingest**: use e.g. `nomctl ingest csv --dataset <RID>` to add to an existing dataset rather than creating a new one. Skip asset/run creation.

## Quick command reference

```sh
# Auth
nomctl config profile add <NAME> --url <URL> --token <TOKEN> [--workspace-rid <RID>]
nomctl user who-am-i

# Discovery (idempotent reads). Prefer `search` over `list` on non-trivial workspaces.
nomctl asset search   --substring <TEXT> [--label L]... [--property K V]...
nomctl run search     --substring <TEXT> [--label L]... [--property K V]...
nomctl asset get <RID> ;  nomctl run get <RID> ;  nomctl dataset get <RID>
nomctl asset list ; nomctl run list ; nomctl dataset list   # workspace-wide dump; use sparingly

# Create
nomctl asset create   --name <N> [--description ...] [--label L]... [--property K V]...
nomctl run create     --name <N> --start <RFC3339> [--end <RFC3339>] [--asset <RID>]... [--label L]... [--property K V]...
nomctl dataset create --name <N> ...   # only if you need an empty dataset; ingest creates one atomically
nomctl video create   --name <N> ...

# Ingest — every form takes either --name <NEW_NAME> or --dataset/--video <EXISTING_RID>.
# First file in a bucket uses --name. Subsequent files from the same source
# append with --dataset / --video. Waits by default; pass --no-wait to detach.
nomctl ingest csv                 <PATH> {--name <N> | --dataset <RID>} --timestamp-column <COL> --timestamp-type <SPEC> [--timestamp-offset <RFC3339>]
nomctl ingest parquet             <PATH> {--name <N> | --dataset <RID>} --timestamp-column <COL> --timestamp-type <SPEC> [--archive]
nomctl ingest mcap                <PATH> {--name <N> | --dataset <RID>} [--include-topic <T>]... [--exclude-topic <T>]... [--ignore-invalid-topics]
nomctl ingest mcap-video          <PATH> {--name <N> | --video   <RID>} --topic <TOPIC>     # foxglove.CompressedVideo or raw H.264 only
nomctl ingest journal-json        <PATH> {--name <N> | --dataset <RID>} [--channel <NAME>]
nomctl ingest ardupilot-dataflash <PATH> {--name <N> | --dataset <RID>}
nomctl ingest video               <PATH> {--name <N> | --video   <RID>} --start <RFC3339>

# Attach (run once per dataset/video, not once per file ingested into it)
nomctl asset add-dataset    <ASSET_RID> <SCOPE_NAME> <DATASET_RID>     # preferred when asset exists
nomctl asset add-video      <ASSET_RID> <SCOPE_NAME> <VIDEO_RID>
nomctl asset add-connection <ASSET_RID> <SCOPE_NAME> <CONNECTION_RID>
nomctl run   add-dataset    <RUN_RID>   <REF_NAME>   <DATASET_RID>     # only when no asset
nomctl run   add-video      <RUN_RID>   <REF_NAME>   <VIDEO_RID>
nomctl run   add-connection <RUN_RID>   <REF_NAME>   <CONNECTION_RID>

# Update metadata
nomctl asset update   <RID> [-n NAME] [-d DESC] [-l LABEL]... [-p K V]... [--clear-labels] [--clear-properties]
nomctl run update     <RID> ...
nomctl dataset update <RID> ...

# Channels (optional polish)
nomctl channel list   <DATA_SOURCE_RID>
nomctl channel set    <DATA_SOURCE_RID> <CHANNEL> [--description ...] [--unit ...]
```

**`nomctl api` is off-limits to this skill.** It's a raw REST/gRPC escape hatch intended for humans manually probing the API. Endpoints reached this way can have destructive, irreversible side effects (archive, delete, configuration changes, cross-tenant operations) with none of the guard-rails the dedicated subcommands have. If a task seems to require an endpoint that doesn't have a `nomctl <subcommand>` for it — stop and ask the user. Do not call `nomctl api`, `nomctl endpoint list`, or any other raw-endpoint tool to "work around" a missing subcommand.

Always run `nomctl <subcommand> --help` if you're unsure about a flag. The CLI is the source of truth — this skill can drift.
