# Ingest plan template

Show the user one complete plan and wait for an explicit go:

```md
## Ingest plan for <folder>

Profile: <name> · Workspace: <rid>
Session: <ingest_session_id>

### Assets
- create: <name> — labels: [...] properties: {...}
- reuse: <RID> (<name>) — confirmed by user

### Runs
- <name> — assets: [...]
  - start: <RFC3339> [source: sidecar | data-min | folder-date | mtime]
  - end: <RFC3339> [source: sidecar | data-max | folder-date | start+duration]
  - labels: [...] properties: {...}

### Datasets
- owner: <asset | run>; scope: <stable_snake_case>
  - resource: create <name> | reuse <RID>
  - format: <format>
  - timestamps: <column/type/offset, or native>
  - MCAP topics: include=[...] exclude=[video topics]
  - files, in order: <file 1>, <file 2>, ...

### Videos
- owner: <asset | run>; scope: <stable_snake_case>
  - resource: create <name> | reuse <RID>
  - source: standalone | mcap-topic <topic>
  - files, in order: <file> — start: <RFC3339> [source: ...]

### Things I'm unsure about
- <question the user must answer before ingest>
```

For each source bucket, the plan must state the owner, reuse decision, scope, ingest order, format-specific options, and all start/end or timestamp evidence. A run with an asset gets data attached to that asset; a run without one owns its data directly.
