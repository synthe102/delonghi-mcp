"""FastMCP server for controlling a De'Longhi coffee machine."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from mcp.server.fastmcp import Context, FastMCP

from delonghi_mcp.ayla_client import AylaClient
from delonghi_mcp.config import AylaSettings
from delonghi_mcp.exceptions import DeLonghiMCPError
from delonghi_mcp.protocol import (
    RECIPE_IDS,
    RECIPE_NAMES,
    STATUS_PROPERTIES,
    build_brew_command,
    build_connect_command,
    build_init_command,
    build_power_on_command,
    extract_device_suffix,
    parse_stored_recipe,
    stored_to_brew_params,
)


@dataclass
class AppContext:
    client: AylaClient
    settings: AylaSettings
    selected_dsn: str | None = None
    device_suffix: bytes | None = None
    recipe_cache: dict[int, bytes] | None = None


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    settings = AylaSettings()
    async with httpx.AsyncClient(timeout=30.0) as http_client:
        client = AylaClient(http_client, settings)
        if settings.is_configured() or client.has_saved_credentials():
            try:
                await client.authenticate()
            except Exception:
                pass  # Tools will re-attempt via _ensure_auth
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
    await app.client.set_property(
        "app_device_connected", build_connect_command(suffix), dsn
    )
    await app.client.set_property("app_data_request", build_init_command(suffix), dsn)


async def _get_brew_params(app: AppContext) -> dict[int, bytes]:
    """Fetch and cache brew parameters for all stored recipes.

    Reads all device properties, finds profile-1 recipe properties,
    parses each stored recipe, and converts to brew command format.
    """
    if app.recipe_cache is not None:
        return app.recipe_cache

    all_props = await app.client.get_device_properties(app.selected_dsn)
    cache: dict[int, bytes] = {}
    for prop in all_props:
        if not (prop.name.startswith("d") and "_rec_1_" in prop.name and prop.value):
            continue
        try:
            _profile_id, recipe_id, stored_params = parse_stored_recipe(prop.value)
            cache[recipe_id] = stored_to_brew_params(stored_params)
        except (ValueError, IndexError):
            continue

    app.recipe_cache = cache
    return cache


def _truncate(value: object, max_len: int = 80) -> str:
    s = repr(value)
    return s if len(s) < max_len else s[: max_len - 3] + "..."


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
    except DeLonghiMCPError as e:
        return f"ERROR: {e}"

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
# Tool: power_on
# ---------------------------------------------------------------------------


@mcp.tool()
async def power_on(ctx: Context, dsn: str | None = None) -> str:
    """Wake the coffee machine from standby.

    Sends the power-on command (0x840F) to bring the machine out of
    sleep/standby mode. The machine needs a moment to heat up before
    it can brew.
    """
    app = _get_ctx(ctx)
    dsn = dsn or app.selected_dsn

    try:
        await _connect_to_machine(app)
        suffix = await _ensure_device_suffix(app)
        command = build_power_on_command(suffix)
        result = await app.client.set_property("app_data_request", command, dsn)
        return f"Power-on command sent.\nResponse: {result}"
    except DeLonghiMCPError as e:
        return f"ERROR: {e}"


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
        if prop is None:
            lines.append(f"  {label}: (unavailable)")
        elif prop_name == "d512_percentage_to_deca" and isinstance(prop.value, int):
            if prop.value > 100:
                lines.append(
                    f"  {label}: {prop.value}% — DESCALING OVERDUE "
                    f"({prop.value - 100}% past threshold)"
                )
            else:
                lines.append(f"  {label}: {prop.value}%")
        else:
            lines.append(f"  {label}: {prop.value}")

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

    Automatically discovers all available recipes from the machine.

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

    try:
        brew_params = await _get_brew_params(app)
    except DeLonghiMCPError as e:
        return f"ERROR fetching recipes: {e}"

    if recipe_id not in brew_params:
        available = "\n".join(
            f"  - {RECIPE_NAMES.get(rid, f'ID 0x{rid:02X}')}"
            for rid in sorted(brew_params)
        )
        return (
            f"ERROR: '{beverage_name}' recipe not found on the machine.\n\n"
            f"Available recipes:\n{available}"
        )

    try:
        await _connect_to_machine(app)
        suffix = await _ensure_device_suffix(app)
        command = build_brew_command(recipe_id, brew_params[recipe_id], suffix)
        result = await app.client.set_property("app_data_request", command, dsn)
        return (
            f"Brewing {beverage_name}!\nCommand sent successfully.\nResponse: {result}"
        )
    except DeLonghiMCPError as e:
        return f"ERROR brewing {beverage_name}: {e}"


# ---------------------------------------------------------------------------
# Tool: list_beverages
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_beverages(ctx: Context) -> str:
    """List all beverages available on the machine.

    Reads stored recipes directly from the machine to show what can be brewed.
    """
    app = _get_ctx(ctx)

    try:
        brew_params = await _get_brew_params(app)
    except DeLonghiMCPError as e:
        return f"ERROR fetching recipes: {e}"

    lines = ["Available beverages:\n"]
    for recipe_id in sorted(brew_params):
        name = RECIPE_NAMES.get(recipe_id, f"Unknown (0x{recipe_id:02X})")
        lines.append(f"  {name} (ID 0x{recipe_id:02X})")

    lines.append(f"\n{len(brew_params)} beverages ready to brew.")
    return "\n".join(lines)
