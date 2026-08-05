# Contributing

Thanks for contributing to Nominal's open agent skills.

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

## Test locally

Before opening a PR:

1. Install the skill from your checkout with the agent's local skills directory,
   for example:

   ```sh
   mkdir -p .agents/skills
   cp -R skills/<name> .agents/skills/
   ```

2. Start or reload your coding agent and verify that it lists the skill.
3. Invoke it with `/<name>` (or the agent's equivalent) using a small,
   representative request.
4. Check that it follows the documented workflow, asks for required approval,
   and does not invent missing information.
5. Review links, commands, and referenced files from a clean checkout.
6. Run the repository validator:

   ```sh
   python3 scripts/validate_skills.py
   ```

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
