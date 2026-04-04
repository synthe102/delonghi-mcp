"""FastMCP server for controlling a De'Longhi coffee machine."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from mcp.server.fastmcp import Context, FastMCP

from delonghi_mcp.ayla_client import AylaClient
from delonghi_mcp.config import AylaSettings
from delonghi_mcp.exceptions import DeLonghiMCPError, NotAuthenticatedError
from delonghi_mcp.protocol import (
    CAPTURED_BREW_PARAMS,
    RECIPE_IDS,
    RECIPE_NAMES,
    STATUS_PROPERTIES,
    build_brew_command,
    build_connect_command,
    build_init_command,
    extract_device_suffix,
)


@dataclass
class AppContext:
    client: AylaClient
    settings: AylaSettings
    selected_dsn: str | None = None
    device_suffix: bytes | None = None


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    settings = AylaSettings()
    async with httpx.AsyncClient(timeout=30.0) as http_client:
        client = AylaClient(http_client, settings)
        yield AppContext(client=client, settings=settings)


mcp = FastMCP("delonghi-coffee", lifespan=lifespan)


def _get_ctx(ctx: Context) -> AppContext:
    return ctx.request_context.lifespan_context


async def _ensure_device_suffix(app: AppContext) -> bytes:
    if app.device_suffix:
        return app.device_suffix
    prop = await app.client.get_property("app_device_connected", app.selected_dsn)
    if not prop.value:
        raise DeLonghiMCPError("Cannot read app_device_connected property.")
    app.device_suffix = extract_device_suffix(prop.value)
    return app.device_suffix


async def _connect_to_machine(app: AppContext) -> None:
    """Establish connection with the machine (required before sending commands)."""
    suffix = await _ensure_device_suffix(app)
    dsn = app.selected_dsn
    await app.client.set_property("app_device_connected", build_connect_command(suffix), dsn)
    await app.client.set_property("app_data_request", build_init_command(suffix), dsn)


def _truncate(value: object, max_len: int = 80) -> str:
    s = repr(value)
    return s if len(s) < max_len else s[: max_len - 3] + "..."


# ---------------------------------------------------------------------------
# Tool: authenticate
# ---------------------------------------------------------------------------


@mcp.tool()
async def authenticate(ctx: Context) -> str:
    """Login to the De'Longhi / Ayla IoT cloud.

    Uses SSO token auth (DELONGHI_AYLA_SSO_TOKEN) if set, otherwise falls
    back to email/password (DELONGHI_AYLA_EMAIL + DELONGHI_AYLA_PASSWORD).
    Both methods require DELONGHI_AYLA_APP_ID and DELONGHI_AYLA_APP_SECRET.
    """
    app = _get_ctx(ctx)

    if not app.settings.is_configured() and not app.client.has_saved_credentials():
        return (
            "ERROR: Missing credentials. Set these environment variables:\n"
            "  DELONGHI_AYLA_APP_ID\n"
            "  DELONGHI_AYLA_APP_SECRET\n"
            "  DELONGHI_AYLA_SSO_TOKEN  (preferred — Gigya JWT from Coffee Link app)\n"
            "  — or —\n"
            "  DELONGHI_AYLA_EMAIL + DELONGHI_AYLA_PASSWORD\n\n"
            "See docs/reverse-engineering-guide.md for how to obtain these values."
        )

    try:
        auth = await app.client.authenticate()
        return (
            f"Authenticated successfully.\n"
            f"Token expires at: {auth.expires_at.isoformat()}\n"
            f"Role: {auth.role or 'N/A'}"
        )
    except DeLonghiMCPError as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Tool: list_devices
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_devices(ctx: Context) -> str:
    """List all De'Longhi coffee machines connected to this account.

    Returns device serial numbers (DSN), models, and connection status.
    If only one device is found, it is auto-selected for all future commands.
    """
    app = _get_ctx(ctx)
    try:
        devices = await app.client.list_devices()
    except NotAuthenticatedError as e:
        return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR listing devices: {e}"

    if not devices:
        return "No devices found on this account."

    if len(devices) == 1:
        app.selected_dsn = devices[0].dsn

    lines = [f"Found {len(devices)} device(s):\n"]
    for d in devices:
        lines.append(f"  DSN: {d.dsn}")
        lines.append(f"  Product: {d.product_name}")
        lines.append(f"  Model: {d.model}")
        if d.oem_model:
            lines.append(f"  OEM Model: {d.oem_model}")
        lines.append(f"  Status: {d.connection_status}")
        if d.lan_ip:
            lines.append(f"  LAN IP: {d.lan_ip}")
        if d.connected_at:
            lines.append(f"  Last connected: {d.connected_at}")
        lines.append("")

    if len(devices) == 1:
        lines.append(f"Auto-selected device: {devices[0].dsn}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool: machine_status (bulk fetch, no N+1)
# ---------------------------------------------------------------------------


@mcp.tool()
async def machine_status(ctx: Context, dsn: str | None = None) -> str:
    """Get the coffee machine's current status.

    Shows machine state, grounds container level, descaling status,
    beverage counters, and other key metrics.
    """
    app = _get_ctx(ctx)
    dsn = dsn or app.selected_dsn

    try:
        all_props = await app.client.get_device_properties(dsn)
    except DeLonghiMCPError as e:
        return f"ERROR: {e}"

    props_by_name = {p.name: p for p in all_props}

    lines = ["Machine Status:\n"]
    for prop_name, label in STATUS_PROPERTIES.items():
        prop = props_by_name.get(prop_name)
        lines.append(f"  {label}: {prop.value if prop else '(unavailable)'}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool: get_all_properties
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_all_properties(ctx: Context, dsn: str | None = None) -> str:
    """Read ALL properties from a coffee machine.

    This is the full discovery tool — returns every property the machine
    exposes. For a quick status overview, use machine_status instead.
    """
    app = _get_ctx(ctx)
    dsn = dsn or app.selected_dsn

    try:
        props = await app.client.get_device_properties(dsn)
    except DeLonghiMCPError as e:
        return f"ERROR: {e}"

    if not props:
        return "No properties found on this device."

    inputs = [p for p in props if p.direction == "input"]
    outputs = [p for p in props if p.direction == "output"]

    lines = [f"Device properties ({len(props)} total):\n"]

    if outputs:
        lines.append(f"--- Status properties (readable, {len(outputs)}) ---")
        for p in outputs:
            lines.append(f"  {p.name} = {_truncate(p.value)}  [{p.type}]")
        lines.append("")

    if inputs:
        lines.append(f"--- Command properties (writable, {len(inputs)}) ---")
        for p in inputs:
            lines.append(f"  {p.name} = {_truncate(p.value)}  [{p.type}]")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool: get_property
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_property(
    ctx: Context, property_name: str, dsn: str | None = None
) -> str:
    """Read a specific property value from the coffee machine."""
    app = _get_ctx(ctx)
    dsn = dsn or app.selected_dsn

    try:
        prop = await app.client.get_property(property_name, dsn)
    except DeLonghiMCPError as e:
        return f"ERROR: {e}"

    return (
        f"Property: {prop.name}\n"
        f"Value: {prop.value!r}\n"
        f"Type: {prop.type}\n"
        f"Direction: {prop.direction}\n"
        f"Read-only: {prop.read_only}\n"
        f"Updated at: {prop.updated_at or 'N/A'}"
    )


# ---------------------------------------------------------------------------
# Tool: set_property
# ---------------------------------------------------------------------------


@mcp.tool()
async def set_property(
    ctx: Context,
    property_name: str,
    value: str,
    dsn: str | None = None,
) -> str:
    """Set a device property to a specific value.

    The value is auto-parsed: integers and floats are detected automatically,
    otherwise it is sent as a string.
    """
    app = _get_ctx(ctx)
    dsn = dsn or app.selected_dsn

    parsed_value: int | float | str = value
    try:
        parsed_value = int(value)
    except ValueError:
        try:
            parsed_value = float(value)
        except ValueError:
            pass

    try:
        result = await app.client.set_property(property_name, parsed_value, dsn)
    except DeLonghiMCPError as e:
        return f"ERROR: {e}"

    return f"Set {property_name} = {parsed_value!r}\nResponse: {result}"


# ---------------------------------------------------------------------------
# Tool: brew_coffee
# ---------------------------------------------------------------------------


def _resolve_recipe_id(beverage: str) -> int | None:
    normalized = beverage.lower().strip().replace("-", " ").replace("_", " ")
    # Exact match
    if normalized in RECIPE_IDS:
        return RECIPE_IDS[normalized]
    # Partial match
    for name, rid in RECIPE_IDS.items():
        if normalized in name or name in normalized:
            return rid
    return None


@mcp.tool()
async def brew_coffee(
    ctx: Context,
    beverage: str,
    dsn: str | None = None,
) -> str:
    """Brew a specific beverage using the machine's current profile settings.

    Currently supported: espresso, regular coffee.
    More beverages can be added by capturing their brew commands from the
    Coffee Link app via MITM proxy.

    WARNING: This will physically operate the coffee machine. Make sure it
    has water, beans, and a cup in place before brewing.
    """
    app = _get_ctx(ctx)
    dsn = dsn or app.selected_dsn

    recipe_id = _resolve_recipe_id(beverage)
    if recipe_id is None:
        available = "\n".join(f"  - {name}" for name in sorted(RECIPE_IDS.keys()))
        return f"ERROR: Unknown beverage '{beverage}'.\n\nAvailable:\n{available}"

    beverage_name = RECIPE_NAMES.get(recipe_id, beverage)

    if recipe_id not in CAPTURED_BREW_PARAMS:
        captured = "\n".join(
            f"  - {RECIPE_NAMES[rid]}" for rid in sorted(CAPTURED_BREW_PARAMS)
        )
        return (
            f"ERROR: '{beverage_name}' brew command has not been captured yet.\n\n"
            f"Currently available:\n{captured}\n\n"
            "To add more beverages, brew them from the Coffee Link app while "
            "running mitmproxy, then add the captured params to protocol.py "
            "CAPTURED_BREW_PARAMS."
        )

    try:
        await _connect_to_machine(app)
        suffix = await _ensure_device_suffix(app)
        command = build_brew_command(recipe_id, CAPTURED_BREW_PARAMS[recipe_id], suffix)
        result = await app.client.set_property("app_data_request", command, dsn)
        return f"Brewing {beverage_name}!\nCommand sent successfully.\nResponse: {result}"
    except DeLonghiMCPError as e:
        return f"ERROR brewing {beverage_name}: {e}"


# ---------------------------------------------------------------------------
# Tool: list_beverages
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_beverages(ctx: Context) -> str:
    """List all known beverage types and their availability.

    Beverages marked READY have captured brew commands and can be brewed.
    Others need their commands captured from the Coffee Link app first.
    """
    lines = ["Available beverages:\n"]
    for recipe_id, name in sorted(RECIPE_NAMES.items(), key=lambda x: x[1]):
        status = "READY" if recipe_id in CAPTURED_BREW_PARAMS else "needs capture"
        lines.append(f"  {name} (ID 0x{recipe_id:02X}) [{status}]")

    ready = len(CAPTURED_BREW_PARAMS)
    total = len(RECIPE_NAMES)
    lines.append(f"\n{ready}/{total} beverages ready to brew.")
    if ready < total:
        lines.append(
            "To add more, brew them from the Coffee Link app while running "
            "mitmproxy, then add the captured params to protocol.py."
        )

    return "\n".join(lines)
