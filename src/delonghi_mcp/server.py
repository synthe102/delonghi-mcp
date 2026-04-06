"""FastMCP server for controlling a De'Longhi coffee machine."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.fastmcp import Context, FastMCP

from delonghi_mcp.api import DeLonghiAPI
from delonghi_mcp.exceptions import DeLonghiMCPError
from delonghi_mcp.protocol import STATUS_PROPERTIES


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[DeLonghiAPI]:
    async with DeLonghiAPI() as api:
        yield api


mcp = FastMCP("delonghi-coffee", lifespan=lifespan)


def _get_api(ctx: Context) -> DeLonghiAPI:
    return ctx.request_context.lifespan_context


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
    api = _get_api(ctx)
    try:
        devices = await api.list_devices()
    except DeLonghiMCPError as e:
        return f"ERROR: {e}"

    if not devices:
        return "No devices found on this account."

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
    api = _get_api(ctx)
    try:
        result = await api.power_on(dsn)
        return f"Power-on command sent.\nResponse: {result}"
    except DeLonghiMCPError as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Tool: machine_status
# ---------------------------------------------------------------------------


@mcp.tool()
async def machine_status(ctx: Context, dsn: str | None = None) -> str:
    """Get the coffee machine's current status.

    Shows machine state, grounds container level, descaling status,
    beverage counters, and other key metrics.
    """
    api = _get_api(ctx)
    try:
        status = await api.get_machine_status(dsn)
    except DeLonghiMCPError as e:
        return f"ERROR: {e}"

    lines = ["Machine Status:\n"]
    for label, prop in status.items():
        if prop is None:
            lines.append(f"  {label}: (unavailable)")
        elif label == STATUS_PROPERTIES.get("d512_percentage_to_deca") and isinstance(
            prop.value, int
        ):
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
    api = _get_api(ctx)
    try:
        props = await api.get_all_properties(dsn)
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


@mcp.tool()
async def brew_coffee(
    ctx: Context,
    beverage: str,
    dsn: str | None = None,
    coffee_quantity_ml: int | None = None,
    milk_quantity_ml: int | None = None,
    water_quantity_ml: int | None = None,
    intensity: int | None = None,
) -> str:
    """Brew a specific beverage, optionally overriding recipe settings.

    Automatically discovers all available recipes from the machine.

    Args:
        beverage: Name of the beverage to brew (e.g. "espresso", "cappuccino").
        dsn: Device serial number. Uses auto-selected device if omitted.
        coffee_quantity_ml: Coffee amount in ml (e.g. 40 for espresso, 180 for regular).
        milk_quantity_ml: Milk amount in ml. Only available for milk-based drinks.
        water_quantity_ml: Water amount in ml. Only available for americano, hot water, tea.
        intensity: Coffee strength from 1 (mild) to 5 (extra strong).

    WARNING: This will physically operate the coffee machine. Make sure it
    has water, beans, and a cup in place before brewing.
    """
    api = _get_api(ctx)
    try:
        result = await api.brew(
            beverage,
            dsn,
            coffee_quantity_ml=coffee_quantity_ml,
            milk_quantity_ml=milk_quantity_ml,
            water_quantity_ml=water_quantity_ml,
            intensity=intensity,
        )
        return (
            f"Brewing {result.beverage_name}!\n"
            f"Command sent successfully.\nResponse: {result.response}"
        )
    except ValueError as e:
        return f"ERROR: {e}"
    except DeLonghiMCPError as e:
        return f"ERROR brewing: {e}"


# ---------------------------------------------------------------------------
# Tool: list_beverages
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_beverages(ctx: Context) -> str:
    """List all beverages available on the machine.

    Reads stored recipes directly from the machine to show what can be brewed.
    """
    api = _get_api(ctx)
    try:
        beverages = await api.list_beverages()
    except DeLonghiMCPError as e:
        return f"ERROR fetching recipes: {e}"

    lines = ["Available beverages:\n"]
    for recipe_id, name in beverages.items():
        lines.append(f"  {name} (ID 0x{recipe_id:02X})")

    lines.append(f"\n{len(beverages)} beverages ready to brew.")
    return "\n".join(lines)
