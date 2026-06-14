# @erdo/magpie

CLI and MCP stdio server for [Magpie](../README.md) — the knowledge and context store for agents and teams.

```bash
npx @erdo/magpie login                 # email OTP → access token stored in ~/.config/magpie/
magpie link --workspace reach --project alertee

magpie search "landing page brand assets"
magpie read <entry-id> --resolved
magpie write --title "Alertee positioning" --file positioning.md
magpie archive <entry-id>

magpie kv list
magpie kv get reach.strategy alertee
magpie kv set reach.strategy alertee --file strategy.json

magpie attachments add <entry-id> ./logo.svg --role logo-primary
magpie attachments list <entry-id>

magpie import ./docs --workspace erdo --project magpie
magpie mcp                            # MCP stdio server for local agents
```

Config: `MAGPIE_API_URL` (default `https://magpie.erdo.ai`), `MAGPIE_TOKEN` (overrides stored token), `~/.config/magpie/config.json` for linked workspace/project.

## Claude Code

```bash
claude mcp add magpie -- npx @erdo/magpie mcp
```

## Development

```bash
yarn install
yarn dev --help     # run from source
yarn build          # compile to dist/
```
