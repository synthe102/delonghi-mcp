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

- **`protocol.py`** — Binary packet construction: CRC-16/CCITT, brew/init/connect commands, recipe ID mappings. All commands go through a single Ayla property (`app_data_request`) as base64-encoded binary. Recipe parameters use a **Type-Value (TV) pair** encoding; `stored_to_brew_params()` converts stored recipe format to brew command format automatically.

- **`ayla_client.py`** — Async HTTP client for Ayla's REST API. Handles three auth methods (persisted refresh token -> SSO token -> email/password) with automatic token refresh. Persists the refresh token to `.ayla_token.json` so the SSO token is only needed once.

- **`server.py`** — FastMCP tool definitions. Before brewing, must run the 3-step connection flow: handshake (`app_device_connected`) -> init command (0xE8F0) -> brew command (0x83F0). Skipping the handshake causes the machine to acknowledge but not execute commands.

- **`config.py`** — Pydantic-settings loading credentials from env vars prefixed `DELONGHI_`.

### Binary protocol essentials

Packet: `[0x0D] [len] [payload] [CRC16] [4B timestamp BE] [4B device suffix BE]`

- `len = len(payload) + 3`
- CRC-16/CCITT (init 0x1D0F) over `[0x0D, len, ...payload]`
- Device suffix: constant 4 bytes extracted from `app_device_connected` property
- Stored recipe params (d059_rec_1_* properties) use **TV pairs** with different ordering than brew commands — `stored_to_brew_params()` handles the conversion (drop type 0x19, add type 0x27, sort ascending, append 0x06). Types 0x01/0x09/0x0F have 2-byte values (quantities in ml), others have 1-byte values.

### Testing

Tests use `respx` to mock `httpx` requests. The `ayla_client` fixture in `conftest.py` uses an isolated temp-dir token file to avoid interfering with real credentials. Protocol tests verify CRC and reproduce captured commands byte-for-byte.
