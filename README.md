# Nominal agent skills

Nominal's [agent skills](https://agentskills.io/specification): packaged instructions that coding agents can load to perform a focused task.

## Skills

| Skill | What it does | Instructions |
| --- | --- | --- |
| `nominal-ingest` | Plans and executes ingestion of a folder of test or campaign data into Nominal. | [`SKILL.md`](skills/nominal-ingest/SKILL.md) |
| `connect-app` | Scaffolds a Nominal Connect app (`app.connect` UI + Python scripts) from a description of its UI and behavior. | [`SKILL.md`](skills/connect-app/SKILL.md) |

How you invoke a skill depends on the host — see [Invoke](#invoke). Installed, enabled skills
can also be selected automatically when your request matches their description and the host
allows implicit invocation.

## Install

Choose the section for your agent. For `npx skills add`, installation is project-local by
default; add `-g` for a user-level installation. Native plugin installation uses the host's
marketplace and workspace controls instead.

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

ChatGPT supports skills packaged in plugins. Workspace admins can import this repository
through [GitHub marketplace import](https://learn.chatgpt.com/docs/enterprise/plugin-management):

1. Open **Admin → Plugins → Add → Import marketplace**.
2. Set **Source** to `https://github.com/nominal-io/skills` and leave **Path** empty.
3. Leave **Branch, tag, or commit** empty for the default branch, or select the revision
   you intend to test. An unmerged PR requires its branch or commit.
4. Import the marketplace, authorize GitHub access if prompted, and review the import results.
5. Configure access to **Nominal Skills** for the intended workspace members. Members with
   access can install the plugin, start a new chat, and select its skills with `@`.

The repository's `.agents/plugins/marketplace.json` and `.codex-plugin/plugin.json` use a
[documented supported layout](https://learn.chatgpt.com/docs/enterprise/plugin-management#supported-formats).
This route requires workspace administration access and availability of the import controls.
Importing this specific package into a clean ChatGPT workspace has not yet been verified;
public plugin-directory publication is not required for workspace import.

For local development in ChatGPT Work, OpenAI also documents using `@plugin-creator` to add
an existing plugin folder to a local marketplace, then installing and testing it in a new
conversation. See [Build plugins](https://learn.chatgpt.com/docs/build-plugins). Standalone
local skill folders and workspace plugin imports are different installation routes; do not
assume a local folder is accessible from a web or mobile session.

The Codex command below configures a Codex marketplace; it does not perform the ChatGPT
workspace import above. If your ChatGPT surface lacks these controls, ask your workspace
admin about plugin access or use the local Codex installation route.

### Codex

Install the native Codex plugin from this marketplace:

```sh
codex plugin marketplace add nominal-io/skills
codex plugin add nominal-skills@nominal
```

Start a new session after installation. The plugin includes the `nominal-ingest` and
`connect-app` skills. You can also select the plugin through `/plugins` in Codex CLI.
For the IDE extension, use the direct skill installation below; native plugins are not
available there. See [supported plugin surfaces](https://learn.chatgpt.com/docs/plugins).

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

Copy the whole skill directory, not just its `SKILL.md`: `references/`, `scripts/`,
`assets/`, and optional `agents/` metadata are part of the package. Bundled resource paths
are relative to the installed skill directory.

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

Substitute any installed skill name from the table above. Hosts that support implicit
selection can match your request against the skill description. If selection is unreliable,
invoke the skill explicitly. OpenAI invocation and discovery behavior is documented in
[Build skills](https://learn.chatgpt.com/docs/build-skills).

## Verify

After installing, start or reload your agent, then invoke a skill or just describe the task:

- **`nominal-ingest`** — "Ingest this folder of flight data into Nominal." The agent should
  walk the folder and propose a plan before creating anything, per
  [`SKILL.md`](skills/nominal-ingest/SKILL.md).
- **`connect-app`** — "Build me a Connect app with a plot of engine pressure and a start/stop
  button." The agent should settle the spec — target directory, tabs, scripts, streams and
  topics — before writing files, per [`SKILL.md`](skills/connect-app/SKILL.md).

If the agent doesn't recognize a skill, ask it to list its loaded skills.

## Execution environment

Installing a skill supplies instructions and bundled resources. It does not install Nominal
software, authenticate an account, or grant access to files on another machine.

- **Ingest data:** execution requires access to the source files, `nomctl`, and a configured
  Nominal profile with the necessary permissions. A folder on your laptop is not automatically
  available in a cloud chat. With missing tools, the agent can still help plan from supplied
  file listings and prepare commands for your machine.
- **Build a Connect app:** the agent can author the app files in an environment that supports
  file creation. Running the app requires the Nominal Connect desktop application and any
  devices or services the app uses. Generated files alone do not establish that the app runs.

Use existing authentication configuration; do not paste tokens into a chat. The skills should
report what was actually inspected or executed and what remains for the target environment.

## Prerequisite

`nominal-ingest` uses the [`nomctl` CLI](https://github.com/nominal-io/nominal-client-rs).
Install a release binary from the
[nomctl releases](https://github.com/nominal-io/nominal-client-rs/releases) page and
make `nomctl` available on your `PATH` before using the skill.

Questions or problems? [Open an issue](https://github.com/nominal-io/skills/issues).
