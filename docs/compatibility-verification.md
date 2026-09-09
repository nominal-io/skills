# Compatibility verification

Verified on 2026-09-09 against PR #11 commit `5a344cc` using `codex-cli 0.153.4`.
This records observed behavior, not a promise that every host or account supports every route.

## Native Codex installation

The Nominal marketplace was not configured before this test. These commands succeeded:

```sh
codex plugin marketplace add nominal-io/skills --ref docs/cross-host-skill-support --json
codex plugin add nominal-skills@nominal --json
codex plugin list --marketplace nominal --json
```

The installer reported version `1.0.0` and the plugin ID `nominal-skills@nominal`.
The final listing reported `installed: true` and `enabled: true`. The branch override tests
an unmerged PR; after merge, use the default-branch installation command in the README.

A fresh app-server process was initialized and queried with `skills/list` and
`forceReload: true`. It returned both installed skills from the plugin cache:

| Runtime name | Display name | Metadata loaded |
| --- | --- | --- |
| `nominal-skills:nominal-ingest` | Nominal Ingest | Short description and default prompt |
| `nominal-skills:connect-app` | Nominal Connect Apps | Short description and default prompt |

This exposed the native plugin namespace, which is now included in the README invocation
examples. Direct skill installs use the skill's unqualified name instead.

## Fresh-session behavior

The Connect smoke test used `codex exec --ephemeral --sandbox read-only` and an explicit
`$nominal-skills:connect-app` request. The prompt requested an engine-pressure plot and
Start/Stop controls, stated that the target folder was inaccessible, and prohibited writes
and external services. The recorded command trace showed successful reads of the installed
`skills/connect-app/SKILL.md` and its packaged `references/app_connect_schema.md`, rather
than the repository copies.

The response asked for the pressure source, units, command semantics, stream/topic names,
and dependencies. It offered named file contents when artifact creation was unavailable,
and distinguished reference readability from an app running successfully in Connect.
No application files were generated, and no device or Nominal operation was performed.

This is a narrow invocation/resource/fallback test. It does not validate an entire generated
Connect application or prove that natural-language discovery always chooses the right skill.

A second fresh read-only session used a natural-language request to plan ingestion of
`flight-001/pressure.csv` and `flight-001/video.mp4`, without an explicit skill mention.
It selected the installed ingestion skill and read its packaged `references/data-model.md`.
The response proposed a Run, Dataset, and Video while identifying unknown timestamps,
video synchronization, workspace/profile, and existing resources. It explicitly marked file
contents, authentication, CLI availability, and platform state as unverified. The command
trace contained only reads of installed instruction/reference files. This was a constrained
smoke test, not an exhaustive test of implicit routing.

## Repository checks

```sh
uv run scripts/validate_skills.py
uv run scripts/test_validate_skills.py
```

Both passed. The regression suite covers 15 fixtures: absent/valid metadata and invalid
YAML, sections, keys, and field types. Seven fixtures reproduced failures before the fix.
Claude and Cursor installation sections and native Claude manifests were preserved.

## Still unverified

- ChatGPT workspace GitHub import: the available web browser was signed out; desktop app
  UI automation was unavailable. The README's admin steps are based on the
  [official workspace-import documentation](https://learn.chatgpt.com/docs/enterprise/plugin-management),
  not a completed import in a real workspace.
- ChatGPT Work local-marketplace installation and the rendered skill picker.
- A fresh Claude or Cursor installation and end-to-end execution there.
- Authenticated ingestion, Connect runtime/device behavior, and extractor image execution.

Before claiming live ChatGPT compatibility, an admin should import the intended revision,
verify the import results and member access, install Nominal Skills, start a new chat, and
select a skill through `@`. Exercise an inaccessible-file request as well as a request in
an environment with the actual required tools. Record the surface, revision, result, and
remaining execution limitations here.
