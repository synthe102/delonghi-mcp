# De'Longhi Eletta Explore MCP Server

An MCP (Model Context Protocol) server for controlling a De'Longhi Eletta Explore coffee maker through Claude. Communicates with the machine via the Ayla Networks IoT cloud — the same platform used by the De'Longhi Coffee Link app.

## Setup

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- A De'Longhi Coffee Link account (same credentials you use in the app)
- The `app_id` and `app_secret` extracted from the Coffee Link app (see [reverse-engineering guide](docs/reverse-engineering-guide.md))

### Install

```bash
git clone <this-repo>
cd delonghi-mcp
uv sync
```

### Configure

1. Copy the example env file and fill in your credentials:

```bash
cp .env.example .env
```

2. Edit `.env` with your De'Longhi Coffee Link email/password and the extracted `app_id`/`app_secret`.

3. Optionally customize beverage presets in `config/beverages.toml` and property mappings in `config/properties.toml` after discovering the actual property names.

## Usage

### With Claude Code

Add to your Claude Code settings (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "delonghi": {
      "command": "uv",
      "args": ["--directory", "/path/to/delonghi-mcp", "run", "delonghi-mcp"]
    }
  }
}
```

### With Claude Desktop

Add to your Claude Desktop config:

```json
{
  "mcpServers": {
    "delonghi": {
      "command": "uv",
      "args": ["--directory", "/path/to/delonghi-mcp", "run", "delonghi-mcp"],
      "env": {
        "DELONGHI_AYLA_EMAIL": "your-email@example.com",
        "DELONGHI_AYLA_PASSWORD": "your-password",
        "DELONGHI_AYLA_APP_ID": "your-app-id",
        "DELONGHI_AYLA_APP_SECRET": "your-app-secret"
      }
    }
  }
}
```

### MCP Inspector (Development)

```bash
uv run mcp dev src/delonghi_mcp/server.py
```

## Tools

| Tool | Description |
|------|-------------|
| `authenticate` | Login to the Ayla IoT cloud |
| `list_devices` | Discover connected coffee machines |
| `get_device_status` | Read all properties from the machine (discovery tool) |
| `get_property` | Read a specific property value |
| `set_property` | Write any property (generic/experimental) |
| `brew_coffee` | Brew a beverage from presets |
| `power_on` | Turn on the machine |
| `power_off` | Turn off / standby |
| `list_beverages` | Show configured beverage types |

### Getting Started Workflow

1. **Authenticate**: `authenticate` — logs in with your credentials
2. **Discover devices**: `list_devices` — finds your coffee machine
3. **Explore properties**: `get_device_status` — shows all device properties (this is how you discover the API)
4. **Experiment**: `set_property` — try writing to properties you've identified
5. **Configure**: Update `config/properties.toml` and `config/beverages.toml` with confirmed property names
6. **Brew**: `brew_coffee` — brew from presets once property names are confirmed

## Architecture

```
Claude ─── MCP (stdio) ──→ FastMCP Server
                               │
                          AylaClient (httpx)
                               │
                     Ayla Networks Cloud API
                               │
                    De'Longhi Coffee Machine (WiFi)
```

The server is designed to work in two modes:

- **Discovery mode**: Property names are placeholders. Use `get_device_status` and `set_property` to explore the machine's API.
- **Operational mode**: Property names are confirmed. `brew_coffee`, `power_on`/`power_off` work fully.

## Reverse Engineering

The Ayla `app_id`, `app_secret`, and device property names are not publicly documented. See [docs/reverse-engineering-guide.md](docs/reverse-engineering-guide.md) for instructions on extracting them from the Coffee Link app.

## Development

```bash
# Install with dev dependencies
uv sync --all-groups

# Run tests
uv run pytest

# Run the MCP inspector
uv run mcp dev src/delonghi_mcp/server.py
```
