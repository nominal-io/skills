# Ingest plan template

Show the user one complete plan and wait for an explicit go:

```md
## Ingest plan for <folder>

Profile: <name> · Workspace: <rid>
Session: <ingest_session_id>

### Assets
- create: <name> — labels: [...] properties: {...}
- reuse: <RID> (<name>) — confirmed by user

Create an asset only with positive evidence of a stable, identifiable thing, such as a serial number, vehicle ID, callsign, or a user-supplied name. A date or a generic folder name is not an asset signal. For a small one-off dump, default to one run and no asset.

### Runs
- <name> — assets: [...]
  - start: <RFC3339> [source: sidecar | data-min | folder-date | mtime]
  - end: <RFC3339> [source: sidecar | data-max | folder-date | start+duration]
  - labels: [...] properties: {...}

For historical data, both `start` and `end` are required. Derive `start` from sidecar metadata, the earliest data timestamp, folder-date evidence, or file mtime, in that order. Derive `end` from sidecar metadata, the latest data timestamp, an end date, or a documented duration. If either value remains uncertain, ask before execution.

When a run links to an asset, its datasets and videos attach to that asset. Attach directly to the run only when it has no asset. A source that genuinely spans multiple assets needs an explicit user decision.

### Datasets
- owner: <asset | run>; scope: <stable_snake_case>
  - resource: create <name> | reuse <RID>
  - format: <format>
  - timestamps: <column/type/offset, or native>
  - MCAP topics: include=[...] exclude=[video topics]
  - files, in order: <file 1>, <file 2>, ...

For a new dataset, the first file uses `--name` and establishes its metadata. Later compatible files use `--dataset <RID>` and do not reattach the data source. A stable scope names the producing source, not an individual flight or filename.

### Videos
- owner: <asset | run>; scope: <stable_snake_case>
  - resource: create <name> | reuse <RID>
  - source: standalone | mcap-topic <topic>
  - files, in order: <file> — start: <RFC3339> [source: ...]

For standalone video, every file includes a start time. For MCAP video, record the exact topic and confirm that the schema is supported before execution.

### Things I'm unsure about
- <question the user must answer before ingest>
```

For each source bucket, the plan must state the owner, reuse decision, scope, ingest order, format-specific options, and all start/end or timestamp evidence. A run with an asset gets data attached to that asset; a run without one owns its data directly.

The plan is the approval boundary. Do not start with one "safe" bucket, parallelize a partial plan, or create placeholder resources before the user approves the entire rendered plan.
