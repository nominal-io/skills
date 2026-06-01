# skills

Install Nominal skills:

```sh
npx skills add nominal-io/skills
# or, if you only have git access via SSH:
npx skills add git@github.com:nominal-io/skills.git
```

Note: `npx skills` does not install the skill for Claude code by default, and you have to select it specifically when you `add` the skill.

Test that the skill is installed in your coding agent by typing, e.g. `/nominal-ingest` to see if the agent recognizes the skill.
