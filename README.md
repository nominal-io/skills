# Nominal agent skills

Nominal's [agent skills](https://agentskills.io/specification): packaged instructions that coding agents can load to perform a focused task.

## Skills

| Skill | What it does | Instructions |
| --- | --- | --- |
| `nominal-ingest` | Plans and executes ingestion of a folder of test or campaign data into Nominal. | [`SKILL.md`](skills/nominal-ingest/SKILL.md) |
| `connect-app` | Scaffolds a Nominal Connect app (`app.connect` UI + Python scripts) from a description of its UI and behavior. | [`SKILL.md`](skills/connect-app/SKILL.md) |

How you invoke a skill depends on the host — see [Invoke](#invoke). Every skill also triggers
from a plain description of the task; explicit invocation is the fallback, not the norm.

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

### ChatGPT

**This route has not been verified from a clean ChatGPT session.** These skills use the shared
[agent skills](https://agentskills.io/specification) format that ChatGPT reads, and a skill can
carry optional OpenAI display metadata (`agents/openai.yaml`) — but this repository is not
published in the universal plugin directory, and OpenAI's
[skill documentation](https://learn.chatgpt.com/docs/build-skills) does not document a route
for installing a skill from a GitHub repository into ChatGPT itself. Check the current
documentation before relying on any of this.

The `codex plugin marketplace add` command below is a **Codex** command. It is not a ChatGPT
command, and installing into Codex does not install into ChatGPT.

To load a skill by hand, copy the entire skill directory — `SKILL.md` together with its
`references/` and `scripts/` — into the skills location your surface reads. Copying `SKILL.md`
alone drops the reference material and helper scripts its instructions point at, and the skill
will fail partway through.

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

Copy the whole skill directory, not just its `SKILL.md`: `references/`, `scripts/`, and
`assets/` are part of the package, and a skill's instructions resolve them relative to the
installed skill directory.

Replace `.agents/skills` with the project or user-level skills directory
supported by your agent. For SSH-only Git access:

```sh
npx skills add git@github.com:nominal-io/skills.git
```

## Invoke

Explicit invocation is host-specific:

| Host | Example |
| --- | --- |
| ChatGPT | type `@`, pick the skill, then the request: `@nominal-ingest Ingest this folder of flight data.` |
| Codex CLI / IDE | `$nominal-ingest Ingest this folder of flight data.` (or `/skills` and select it) |
| Claude Code, native plugin | `/nominal-skills:nominal-ingest` |
| Cursor and other slash-command hosts | `/nominal-ingest` |

Substitute any skill name from the table above. Where a host has no invocation syntax,
describing the task is enough — the `description` in each `SKILL.md` is what a host matches on.

## Verify

After installing, start or reload your agent, then invoke a skill or just describe the task:

- **`nominal-ingest`** — "Ingest this folder of flight data into Nominal." The agent should
  walk the folder and propose a plan before creating anything, per
  [`SKILL.md`](skills/nominal-ingest/SKILL.md).
- **`connect-app`** — "Build me a Connect app with a plot of engine pressure and a start/stop
  button." The agent should settle the spec — target directory, tabs, scripts, streams and
  topics — before writing files, per [`SKILL.md`](skills/connect-app/SKILL.md).

If the agent doesn't recognize a skill, ask it to list its loaded skills.

## Prerequisite

`nominal-ingest` uses the [`nomctl` CLI](https://github.com/nominal-io/nominal-client-rs).
Install a release binary from the
[nomctl releases](https://github.com/nominal-io/nominal-client-rs/releases) page and
make `nomctl` available on your `PATH` before using the skill.

Questions or problems? [Open an issue](https://github.com/nominal-io/skills/issues).
