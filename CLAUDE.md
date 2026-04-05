# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync --all-groups        # Install all dependencies
uv run pytest -v            # Run all tests
uv run pytest tests/test_protocol.py -v  # Run a single test file
uv run pytest -k "test_crc" -v           # Run tests matching a pattern
uv run mcp dev src/delonghi_mcp/server.py  # Launch MCP Inspector for interactive testing
uv run delonghi-mcp         # Run the MCP server (stdio transport)
```

### Nix

The project includes a flake using [uv2nix](https://github.com/pyproject-nix/uv2nix).

```bash
nix develop                 # Dev shell with all deps + uv
nix build                   # Build the package
nix run                     # Run the MCP server
```

## Architecture

This is an MCP server that controls a De'Longhi Eletta Explore coffee maker through the Ayla Networks IoT cloud. The machine uses a proprietary binary protocol tunneled as base64 strings through Ayla device properties.

**Data flow:** Claude -> MCP (stdio) -> `server.py` -> `ayla_client.py` -> httpx -> Ayla Cloud API -> Coffee Machine (WiFi)

### Key modules

- **`protocol.py`** — Binary packet construction: CRC-16/CCITT, brew/init/connect/power-on commands, recipe ID mappings. All commands go through a single Ayla property (`app_data_request`) as base64-encoded binary. Recipe parameters use a **Type-Value (TV) pair** encoding; `stored_to_brew_params()` converts stored recipe format to brew command format automatically.

- **`ayla_client.py`** — Async HTTP client for Ayla's REST API. Auth fallback chain: persisted refresh token -> email/password via Gigya (SAP Customer Data Cloud) -> raw SSO token. Gigya auth calls `accounts.login` (with `include=id_token`) to obtain a JWT, then exchanges it for Ayla tokens via `token_sign_in`. Persists the refresh token to `.ayla_token.json` so Gigya/SSO is only needed once. Auto-authenticates on demand in `_ensure_auth()` — no explicit authenticate call needed.

- **`server.py`** — FastMCP tool definitions. Auto-authenticates at startup in `lifespan()`. Before brewing, must run the 3-step connection flow: handshake (`app_device_connected`) -> init command (0xE8F0) -> brew command (0x83F0). Skipping the handshake causes the machine to acknowledge but not execute commands.

- **`config.py`** — Pydantic-settings loading credentials from env vars prefixed `DELONGHI_`.

### Binary protocol essentials

Packet: `[0x0D] [len] [payload] [CRC16] [4B timestamp BE] [4B device suffix BE]`

- `len = len(payload) + 3`
- CRC-16/CCITT (init 0x1D0F) over `[0x0D, len, ...payload]`
- Device suffix: constant 4 bytes extracted from `app_device_connected` property
- Stored recipe params (d059_rec_1_* properties) use **TV pairs** with different ordering than brew commands — `stored_to_brew_params()` handles the conversion (drop type 0x19, add type 0x27, sort ascending, append 0x06). Types 0x01/0x09/0x0F have 2-byte values (quantities in ml), others have 1-byte values. `override_brew_params()` can modify specific TV pair values (quantity/intensity) in the converted brew params before sending.
- Known TV pair types: `0x01` (coffee ml), `0x09` (milk ml), `0x0F` (water ml), `0x02` (intensity 1-5). Not all types are present in every recipe (e.g., espresso has no milk type).
- Known command opcodes: `0x83F0` (brew), `0xE8F0` (init), `0x840F` (power on), `0x950F` (read machine setting — sent by Coffee Link app when opening settings, not a write).

### Testing

Tests use `respx` to mock `httpx` requests. The `ayla_client` fixture in `conftest.py` uses an isolated temp-dir token file to avoid interfering with real credentials. Protocol tests verify CRC and reproduce captured commands byte-for-byte.
