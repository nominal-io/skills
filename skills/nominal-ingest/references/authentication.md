# Authentication

Use a profile that is already configured whenever possible:

```sh
nomctl config profile list
nomctl --profile <PROFILE> user who-am-i
```

Put the chosen profile on every command. Shell calls do not share exports:

```sh
NOMINAL_PROFILE=<PROFILE> nomctl <SUBCOMMAND> ...
```

`nomctl --profile <PROFILE> <SUBCOMMAND> ...` also works, but `--profile` goes before the subcommand. Do not construct a multi-word flag variable and expand it bare.

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
