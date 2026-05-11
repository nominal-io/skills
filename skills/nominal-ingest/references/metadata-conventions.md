# Metadata conventions

Labels and properties are how the user finds resources later. Apply them consistently across every asset, run, and dataset you create — the value is *uniformity across the workspace*, not richness on a single resource.

## Labels vs. properties

- **Label** = ad-hoc free-text tag. Things a human might scribble on a sticky note. Examples: `cracked-propeller`, `needs-review`, `re-run-pending`.
- **Property** = structured key/value strings. The kinds of fields a human would likely want to group by, or pin down with an exact match. Examples: `firmware_version=2.3.1`, `serial_number=SN-0042`, `outcome=pass`, `customer=nasa`.

## Always-applied metadata

Every resource the skill creates gets at minimum:

**Labels:**
- `ingested-by-skill`

**Properties:**
- `ingest_session_id` — a UUID generated once at the start of the skill run and stamped on every resource it creates. Lets the user (and you, on re-ingest) find every resource produced by a single ingest invocation.

Don't add `ingested_at` / `ingested_by` — the platform already records attribution time.

Properties only stick on the **create** ingest (the `--name <NAME>` call). The `--dataset <RID>` / `--video <RID>` append form doesn't accept `--label` / `--property`. Use `nom dataset update` / `nom video update` if you need to revise metadata after creation.

## Conditional metadata

Properties describe the **event** (the test, run, vehicle, operator), not the data inside the file. Channel names, topic lists, schema details, row counts, file sizes, codec info: all data, not metadata. Don't synthesize them.

If the value is available from a sidecar or folder name, add it. If not, skip — never invent.

| Property name      | Source                                                             | Example value                            |
|--------------------|--------------------------------------------------------------------|------------------------------------------|
| `serial_number`    | sidecar (`serial`, `serial_number`, `sn`)                          | `SN-0042`                                |
| `vehicle_id`       | sidecar (`vehicle`, `vehicle_id`)                                  | `voyager-1`                              |
| `firmware_version` | sidecar                                                            | `2.3.1`                                  |
| `git_sha`          | sidecar                                                            | `abc123def`                              |
| `operator`         | sidecar (`operator`, `pilot`, `tester`)                            | `jane.smith@nominal.io`                  |
| `test_plan_id`     | sidecar                                                            | `TP-204`                                 |
| `test_type`        | sidecar (`test_type`, `category`) or folder name (e.g. `*vibration*`) | `vibration`                           |
| `phase`            | sidecar (`phase`)                                                  | `integration`                            |
| `outcome`          | sidecar (`outcome`, `result`, `status`)                            | `pass`                                   |
| `customer`         | sidecar (`customer`)                                               | `nasa`                                   |
| `program`          | sidecar (`program`)                                                | `lunar-gateway`                          |
| `campaign`         | top-level folder name (Shape 3) or sidecar                         | `fleet-test-q1`                          |

Property values: lowercase the value if it's a categorical (`pass`, `vibration`, `integration`); leave it alone if it's a free-form id (`SN-0042`, `TP-204`, `2.3.1`).

## Conditional labels

Labels are reserved for things that genuinely have no key — observations, statuses, ad-hoc tags pulled out of sidecar prose. Examples:

- An observation in `notes.txt` like "rotor hit the deck" → label `rotor-strike`.
- A free-floating tag in a `tags:` array in `metadata.yaml` whose entries don't look like categories → labels.
- A `status` or `note` token like `re-run-pending`, `cracked-propeller`, `flagged`.

When deriving a label from text, normalize: lowercase, replace whitespace and underscores with `-`, drop punctuation that isn't `-`.

If a sidecar contains a `tags` / `labels` array, scan each entry: if it looks like `key:value` or `key=value`, route it to properties; if it's just a phrase, route it to labels.

## Per-resource specifics

### Assets
- All sidecar metadata that describes the asset itself (vehicle id, serial number, hardware revision, customer).
- Don't include run-specific properties on assets — those belong on runs.

### Runs
- All sidecar metadata that describes the run/event (operator, test plan, outcome, mission).

### Datasets / Videos
- The same `ingest_session_id` as everything else.
- Nothing about the data inside the file. No channel lists, topic lists, schema names, row counts, file sizes, formats. Those answers live in the file, not on the resource.

## Don't put these in metadata

- **Tokens, API keys, anything from `~/.config/nominal/config.yml`**: never.
- **Full file paths containing user names if the workspace is shared**: `/Users/alex/...` is fine for a personal workspace, less so for a team. Ask if uncertain.
- **Free-text descriptions over a few hundred characters**: use the resource's `description` field, not a property.
- **Anything binary-encoded or base64**: properties are human-readable strings.

## Re-ingest hygiene

If the user re-runs the skill on a folder you've ingested before (or runs it on a new flight folder for an asset that's already in Nominal):
- **For assets**: search by identifier — `nom asset search --substring <NAME_OR_ID>`, `nom asset search --property serial_number <SN>`, or by the `ingest_session_id` of a prior run. Confirm with the user before reusing.
- **For runs**: `nom run search --substring <FOLDER_NAME>` or by identifying sidecar properties (test plan, date, operator). Each run usually has unique properties from its folder context.
- **For existing datasets/videos on an asset**: don't search globally — fetch the asset and inspect its data sources via `nom asset get <ASSET_RID>`. That lists everything attached and their scope names. If a dataset with the right scope name (e.g. `dataflash`) already exists on the asset, ingest new files into it with `--dataset <RID>`. Don't create a parallel one.
- Offer to update existing resources instead of creating duplicates. `nom run update --label ... --property ...` replaces all labels/properties — when updating, **read the current values first** and merge, don't clobber.
