# Contributing

Thanks for contributing to Nominal's agent skills.

## Add a skill

Create one directory per skill:

```text
skills/<name>/
├── SKILL.md
├── references/   # optional supporting documentation
├── scripts/      # optional helper scripts
└── assets/       # optional files used by the skill
```

`SKILL.md` must begin with YAML frontmatter containing:

```yaml
---
name: <name>
description: <what the skill does and when an agent should use it>
---
```

- `name` must exactly match the skill directory name.
- Write `description` for agent matching: say what the skill does and the user
  requests or situations that should trigger it.
- Keep the main workflow in `SKILL.md`; put detailed, reusable material in
  `references/`.
- Use clear, imperative instructions and define domain-specific terms.
- Make safety boundaries, required approvals, and destructive operations explicit.
- Prefer portable commands and existing repository conventions.

## Support multiple hosts

Keep one shared workflow in `SKILL.md`. Use capability checks instead of assuming that a
particular host has a local shell, Docker, credentials, or access to the user's computer.
Resolve bundled references, scripts, and assets relative to the installed skill location;
write project outputs into the chosen target directory. Explain useful fallback deliverables
when execution is unavailable, and distinguish authored artifacts from verified results.

Optional OpenAI display metadata lives in `agents/openai.yaml` inside each skill:

```yaml
interface:
  display_name: "Example Workflow"
  short_description: "Describe the workflow in a short UI label"
  default_prompt: "Use $example to help me with this workflow."
```

Use the actual skill name in the default prompt. This metadata supplements the shared skill;
other agents do not need it. Keep implicit invocation enabled unless there is a specific
reason to require explicit selection. Declare only real MCP tools as dependencies, not
Python, Docker, desktop applications, or account credentials. See the current
[OpenAI metadata documentation](https://learn.chatgpt.com/docs/build-skills#optional-metadata).

The validator checks supported metadata keys and field types. It does not validate individual
dependency entries, install a plugin, or prove that a host can execute the workflow.

## Test locally

Before opening a PR:

1. Install the skill from your checkout with the agent's local skills directory,
   for example:

   ```sh
   mkdir -p .agents/skills
   cp -R skills/<name> .agents/skills/
   ```

2. Start or reload your coding agent and verify that it lists the skill.
3. Invoke it using the [host-specific syntax](README.md#invoke) and a small,
   representative request. Also try a natural-language request to check discovery.
4. Check that it follows the documented workflow, asks for required approval,
   and does not invent missing information.
5. Review links, commands, and referenced files from a clean checkout.
6. Run the repository validator:

   ```sh
   uv run scripts/validate_skills.py
   ```

7. Exercise a missing-capability case (such as an inaccessible local folder) and confirm
   the agent provides useful next steps without claiming unexecuted work succeeded.
   Record which hosts and installation routes you actually tested in the PR.

## GitHub Actions

- Pin every workflow action to a full 40-character commit SHA with a trailing `# vX.Y.Z` comment.
- Never interpolate user-controlled `${{ ... }}` values directly in `run:` blocks; pass them through `env:`.

## Pull requests

- Keep each PR focused; avoid unrelated formatting or content changes.
- Use a clear, lowercase conventional-commit subject, such as
  `docs: add nominal-ingest skill`.
- Include what you tested locally and call out any environment-specific steps.
- Update the README skill catalog when adding or removing a skill.
- Do not commit credentials, tokens, generated files, or local agent state.
