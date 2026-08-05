# Authentication

Use a profile that is already configured whenever possible:

```sh
nomctl config profile list
nomctl --profile <PROFILE> user who-am-i
```

If `who-am-i` succeeds, keep that profile for the rest of the plan. Do not inspect the folder or create resources until a profile and workspace are known.

Put the chosen profile on every command. Shell calls do not share exports:

```sh
NOMINAL_PROFILE=<PROFILE> nomctl <SUBCOMMAND> ...
```

`nomctl --profile <PROFILE> <SUBCOMMAND> ...` also works, but `--profile` goes before the subcommand. Do not construct a multi-word flag variable and expand it bare.

`NOMINAL_PROFILE` is the default for one command. An inline `--profile` overrides it when a plan must compare two tenants. Never place `--profile` after the subcommand: `nomctl <SUBCOMMAND> --profile <PROFILE>` fails with `unexpected argument`.

## No profile

Never ask the user to paste a token into chat. Ask them to run this in their own terminal, filling in the values:

```sh
nomctl config profile add <NAME> \
  --url https://<API_HOST> \
  --token <TOKEN> \
  --workspace-rid <WORKSPACE_RID>
```

- `<NAME>` is a short profile name such as `prod`.
- `<API_HOST>` is deployment-specific; ask the user. Examples include `api.gov.nominal.io`, `api-staging.gov.nominal.io`, and a self-hosted `api.nominal.<customer-domain>`.
- `<TOKEN>` comes from Nominal user settings → API keys, or the user's SSO/JWT flow. It stays in their terminal.
- `<WORKSPACE_RID>` is required and comes from the intended workspace's settings.

After the user confirms setup, verify it with `nomctl --profile <NAME> user who-am-i` before continuing.

## Workspace boundary

A profile pins every created resource to its configured workspace. Do not try to override the workspace per command. If the planned ingest belongs in another workspace, the user needs a separate profile for it.

Keep tokens out of chat, plans, command transcripts, and final reports. The user enters the token only in their own terminal; the plan records the profile name and workspace RID, never the credential.
