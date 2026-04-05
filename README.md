# De'Longhi Eletta Explore MCP Server

An [MCP](https://modelcontextprotocol.io/) server for controlling a De'Longhi Eletta Explore coffee maker through Agents. Communicates with the machine via the Ayla Networks IoT cloud — the same platform used by the De'Longhi Coffee Link app.

## Setup

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) or [Nix](https://nixos.org/)
- A De'Longhi Coffee Link account (same credentials you use in the app)
- The `app_id` and `app_secret` extracted from the Coffee Link app (see [reverse-engineering guide](docs/reverse-engineering-guide.md))

### Install

#### With uv

```bash
git clone <this-repo>
cd delonghi-mcp
uv sync
```

#### With Nix

```bash
git clone <this-repo>
cd delonghi-mcp
nix develop    # Enter dev shell with all dependencies
nix build      # Build the package
nix run        # Run the MCP server directly
```

### Configure

Copy the example env file and fill in your credentials:

```bash
cp .env.example .env
```

At minimum you need the Ayla app credentials in `.env`:

```env
DELONGHI_AYLA_APP_ID=your-app-id
DELONGHI_AYLA_APP_SECRET=your-app-secret
```

These are extracted from the Coffee Link app — see [docs/reverse-engineering-guide.md](docs/reverse-engineering-guide.md).

#### Authentication

The server supports three authentication methods, tried in this order:

1. **Persisted refresh token** (automatic) — After a successful login, the server saves a refresh token to `.ayla_token.json`. On subsequent launches, it uses this token automatically. No manual intervention needed until the token expires.

2. **Email/password** — Your De'Longhi Coffee Link account credentials. Set `DELONGHI_EMAIL` and `DELONGHI_PASSWORD` in `.env`. The server authenticates via Gigya (the same SSO provider the Coffee Link app uses) to obtain a JWT, then exchanges it for Ayla tokens.

3. **SSO token** — A Gigya JWT captured from the Coffee Link app's `token_sign_in` request via MITM proxy. Set `DELONGHI_AYLA_SSO_TOKEN` in `.env`. This is a fallback for cases where email/password auth doesn't work.

In practice: provide `app_id` + `app_secret` and your email/password for the first login. After that, the persisted refresh token handles re-authentication automatically.


#### Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DELONGHI_AYLA_APP_ID` | Yes | Ayla application ID (extracted from Coffee Link app) |
| `DELONGHI_AYLA_APP_SECRET` | Yes | Ayla application secret |
| `DELONGHI_EMAIL` | No | De'Longhi Coffee Link account email (recommended for initial login) |
| `DELONGHI_PASSWORD` | No | De'Longhi Coffee Link account password |
| `DELONGHI_AYLA_SSO_TOKEN` | No | Gigya JWT for SSO auth (fallback, captured via MITM proxy) |
| `DELONGHI_AYLA_AUTH_BASE_URL` | No | Auth endpoint (default: EU — `https://user-field-eu.aylanetworks.com`) |
| `DELONGHI_AYLA_ADS_BASE_URL` | No | Device API endpoint (default: EU — `https://ads-eu.aylanetworks.com`) |

## Usage

### With Claude Code

Add to your Claude Code MCP settings (`~/.claude.json` or project `.mcp.json`):

```json
{
  "mcpServers": {
    "delonghi": {
      "command": "uv",
      "args": ["--directory", "/path/to/delonghi-mcp", "run", "delonghi-mcp"],
      "env": {
        "DELONGHI_AYLA_APP_ID": "your-app-id",
        "DELONGHI_AYLA_APP_SECRET": "your-app-secret"
      }
    }
  }
}
```

Email/password and SSO token can go in the project's `.env` file instead of the MCP config. Once authenticated, the server persists a refresh token so only `app_id` and `app_secret` are needed in the MCP config long-term.

### With Claude Desktop

Add to your Claude Desktop config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "delonghi": {
      "command": "uv",
      "args": ["--directory", "/path/to/delonghi-mcp", "run", "delonghi-mcp"],
      "env": {
        "DELONGHI_AYLA_APP_ID": "your-app-id",
        "DELONGHI_AYLA_APP_SECRET": "your-app-secret"
      }
    }
  }
}
```

### With Nix

Run directly from the flake (no clone needed):

```bash
nix run github:synthe102/delonghi-mcp
```

Or from a local checkout:

```bash
nix run .
```

For Claude Code / Claude Desktop, point the MCP config at the flake output:

```json
{
  "mcpServers": {
    "delonghi": {
      "command": "nix",
      "args": ["run", "github:synthe102/delonghi-mcp"],
      "env": {
        "DELONGHI_AYLA_APP_ID": "your-app-id",
        "DELONGHI_AYLA_APP_SECRET": "your-app-secret"
      }
    }
  }
}
```

#### As part of a NixOS / Home Manager flake

Add this repository as a flake input and include the package in your system or user packages:

```nix
{
  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    delonghi-mcp.url = "github:synthe102/delonghi-mcp";
    delonghi-mcp.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = { nixpkgs, delonghi-mcp, ... }: {
    # NixOS system configuration
    nixosConfigurations.myhost = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      modules = [{
        environment.systemPackages = [
          delonghi-mcp.packages.x86_64-linux.default
        ];
      }];
    };

    # Or with Home Manager
    homeConfigurations.myuser = home-manager.lib.homeManagerConfiguration {
      # ...
      modules = [{
        home.packages = [
          delonghi-mcp.packages.x86_64-linux.default
        ];
      }];
    };
  };
}
```

Then use `delonghi-mcp` as the command in your MCP config:

```json
{
  "mcpServers": {
    "delonghi": {
      "command": "delonghi-mcp",
      "env": {
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
| `list_devices` | Discover connected coffee machines. Auto-selects the device if only one is found. |
| `power_on` | Wake the machine from standby mode. |
| `machine_status` | Quick status overview: machine state, grounds container level, descaling status, beverage counters. |
| `list_beverages` | Show all beverages available on the machine (discovered from stored recipes). |
| `brew_coffee` | Brew a beverage by name. Optionally override coffee/milk/water quantity (ml) and intensity (1-5). Reads recipe parameters from the machine and applies overrides before brewing. |
| `get_all_properties` | Read every property the machine exposes (full discovery dump). |

### Getting started workflow

Authentication is automatic — the server logs in at startup using your configured credentials and persists a refresh token for future sessions.

1. **`list_devices`** — Finds your coffee machine and auto-selects it.
2. **`power_on`** — Wake the machine if it's in standby.
3. **`machine_status`** — Check the machine is online and ready.
4. **`list_beverages`** — See what drinks are available.
5. **`brew_coffee`** — Brew something. Make sure the machine has water, beans, and a cup in place.

For exploration and development:
- **`get_all_properties`** — Dump every property to understand the machine's full API surface.

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

### Key modules

- **`server.py`** — FastMCP tool definitions with auto-authentication at startup and the 3-step connection flow (handshake -> init -> command).
- **`ayla_client.py`** — Async HTTP client for Ayla's REST API with cascading auth (refresh token -> email/password via Gigya -> raw SSO token), automatic token persistence, and on-demand re-authentication.
- **`protocol.py`** — Binary packet construction: CRC-16/CCITT, brew/init/connect/power-on commands, recipe parsing, and Type-Value pair encoding for recipe parameters.
- **`config.py`** — Pydantic-settings loading credentials from env vars prefixed `DELONGHI_`.

### Binary protocol

The machine uses a proprietary binary protocol tunneled as base64 strings through Ayla device properties. All commands go through the `app_data_request` property.

Packet format: `[0x0D] [len] [payload] [CRC16] [4B timestamp BE] [4B device suffix BE]`

Before sending any brew command, the server must complete a connection handshake — otherwise the machine acknowledges the command but doesn't execute it.

## Development

```bash
# Install with dev dependencies
uv sync --all-groups

# Run tests
uv run pytest -v

# Run the MCP inspector
uv run mcp dev src/delonghi_mcp/server.py
```

### With Nix

```bash
nix develop  # Enters a shell with all deps (including dev) and uv
pytest       # Tests are available directly
```

### Testing

Tests use `respx` to mock `httpx` requests. The `ayla_client` fixture in `conftest.py` uses an isolated temp-dir token file to avoid interfering with real credentials. Protocol tests verify CRC and reproduce captured commands byte-for-byte.

## Reverse Engineering

The Ayla `app_id`, `app_secret`, and device property names are not publicly documented. See [docs/reverse-engineering-guide.md](docs/reverse-engineering-guide.md) for instructions on extracting them from the Coffee Link app.
