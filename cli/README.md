# @magpie/cli

CLI and MCP stdio server for [Magpie](../README.md) — the knowledge and context store for agents and teams.

```bash
npx @magpie/cli login                 # email OTP → API key stored in ~/.config/magpie/
magpie link --workspace reach --project alertee

magpie search "landing page brand assets"
magpie read <entry-id> --resolved
magpie write --title "Alertee positioning" --file positioning.md
magpie archive <entry-id>

magpie collections list
magpie collections get reach.strategy alertee
magpie collections set reach.strategy alertee --file strategy.json

magpie attachments add <entry-id> ./logo.svg --role logo-primary
magpie attachments list <entry-id>

magpie import ./docs --workspace erdo --project magpie
magpie mcp                            # MCP stdio server for local agents
```

Config: `MAGPIE_API_URL` (default `https://magpie.erdo.ai`), `MAGPIE_TOKEN` (overrides stored key), `~/.config/magpie/config.json` for linked workspace/project.

## Claude Code

```bash
claude mcp add magpie -- npx @magpie/cli mcp
```

## Development

```bash
yarn install
yarn dev --help     # run from source
yarn build          # compile to dist/
```
