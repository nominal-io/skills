# Nominal MCP

This plugin connects Claude Code to the Nominal MCP server. Use it to search, read, and edit Nominal workbooks, checklists, runs, assets, and events from Claude Code.

## Install

```bash
claude plugin marketplace add nominal-io/skills
claude plugin install nominal-mcp@nominal
```

## Select your deployment

The plugin asks for your Nominal deployment when you enable it. The default is `api.gov.nominal.io`. To change it, open `/plugin`, select `nominal-mcp`, and set **Nominal deployment**.

| Deployment | API host |
| --- | --- |
| US | `api.gov.nominal.io` |
| EU West | `api.euw2.nominal.io` |
| EU Central | `api.euc1.nominal.io` |
| Canada | `api.cac1.nominal.io` |

## Sign in

Run `/mcp`, select `plugin:nominal-mcp:nominal`, and select **Authenticate**. A browser opens for your organization's sign-in. The plugin uses OAuth with PKCE. It stores no API keys.

The sign-in uses local callback port `54545`. Keep this port free.

## Self-hosted deployments

This plugin supports Nominal-managed deployments only. For a self-hosted deployment, follow [Connect an external MCP client](https://docs.nominal.io/core/documentation/platform/external-mcp-server).
