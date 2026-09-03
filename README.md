# Nominal agent skills

Nominal's [agent skills](https://agentskills.io/specification): packaged instructions that coding agents can load to perform a focused task.

## Skills

| Skill | What it does | Invoke | Instructions |
| --- | --- | --- | --- |
| `nominal-ingest` | Plans and executes ingestion of a folder of test or campaign data into Nominal. | `/nominal-ingest` | [`SKILL.md`](skills/nominal-ingest/SKILL.md) |
| `connect-app` | Scaffolds a Nominal Connect app (`app.connect` UI + Python scripts) from a description of its UI and behavior. | `/connect-app` | [`SKILL.md`](skills/connect-app/SKILL.md) |

## Install

Choose the section for your agent. The commands below install the skill for the current project; add `-g` when you want a user-level installation instead.

### Cursor

Install with the skills CLI:

```sh
npx skills add nominal-io/skills -a cursor
```

Cursor discovers project skills in `.cursor/skills/` (and `.agents/skills/`), and user skills in `~/.cursor/skills/` (and `~/.agents/skills/`). It also supports `.claude/skills/` and `.codex/skills/` for compatibility.

To install globally:

```sh
npx skills add nominal-io/skills -g -a cursor
```

### Codex

Install the native Codex plugin from this marketplace:

```sh
codex plugin marketplace add nominal-io/skills
```

Then install `nominal-skills` from the `nominal` marketplace in Codex. The
plugin includes the `nominal-ingest` and `connect-app` skills.

Alternatively, install the skill directly with the skills CLI:

```sh
npx skills add nominal-io/skills -a codex
```

Codex discovers project skills in `.agents/skills/` and user skills in `~/.agents/skills/`. To install globally:

```sh
npx skills add nominal-io/skills -g -a codex
```

### Claude Code

Install the native Claude Code plugin from this marketplace:

```text
/plugin marketplace add nominal-io/skills
/plugin install nominal-skills@nominal
```

Invoke the installed skill with its plugin namespace:

```text
/nominal-skills:nominal-ingest
```

Alternatively, install the skill directly with the skills CLI:

```sh
npx skills add nominal-io/skills -a claude-code
```

Claude Code discovers project skills in `.claude/skills/` and user skills in `~/.claude/skills/`. To install globally:

```sh
npx skills add nominal-io/skills -g -a claude-code
```

### Any other agent / manual install

The skills CLI supports many agents:

```sh
npx skills add nominal-io/skills
```

If you cannot use `npx`, clone the repository and copy or symlink
`skills/nominal-ingest` into the agent's skills directory:

```sh
git clone https://github.com/nominal-io/skills.git nominal-skills
mkdir -p .agents/skills
cp -R nominal-skills/skills/nominal-ingest .agents/skills/
```

Replace `.agents/skills` with the project or user-level skills directory
supported by your agent. For SSH-only Git access:

```sh
npx skills add git@github.com:nominal-io/skills.git
```

## Verify

After installing, start or reload your agent and ask it to use the skill:

- **Cursor:** type `/nominal-ingest`, or ask for help ingesting a folder of data.
- **Codex:** type `$nominal-ingest` (or `/skills` and select it).
- **Claude Code:** after native plugin installation, type `/nominal-skills:nominal-ingest`.
- **Other agents:** type `/nominal-ingest` if slash commands are supported, or ask the agent to list its loaded skills.

The agent should recognize the skill and follow the planning-first workflow described in
[`SKILL.md`](skills/nominal-ingest/SKILL.md).

## Prerequisite

`nominal-ingest` uses the [`nomctl` CLI](https://github.com/nominal-io/nominal-client-rs).
Install a release binary from the
[nomctl releases](https://github.com/nominal-io/nominal-client-rs/releases) page and
make `nomctl` available on your `PATH` before using the skill.

Questions or problems? [Open an issue](https://github.com/nominal-io/skills/issues).
