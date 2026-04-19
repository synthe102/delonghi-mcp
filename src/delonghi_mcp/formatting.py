"""Human-readable formatting helpers shared by the MCP server and CLI."""

from __future__ import annotations

from typing import Any

from delonghi_mcp.api import BrewResult
from delonghi_mcp.models import DeviceInfo, DeviceProperty
from delonghi_mcp.protocol import STATUS_PROPERTIES


def _truncate(value: object, max_len: int = 80) -> str:
    s = repr(value)
    return s if len(s) < max_len else s[: max_len - 3] + "..."


def format_devices(devices: list[DeviceInfo]) -> str:
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


def format_power_on(response: dict[str, Any]) -> str:
    return f"Power-on command sent.\nResponse: {response}"


def format_status(status: dict[str, DeviceProperty | None]) -> str:
    descaling_label = STATUS_PROPERTIES.get("d512_percentage_to_deca")
    lines = ["Machine Status:\n"]
    for label, prop in status.items():
        if prop is None:
            lines.append(f"  {label}: (unavailable)")
        elif label == descaling_label and isinstance(prop.value, int):
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


def format_properties(props: list[DeviceProperty]) -> str:
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


def format_brew_result(result: BrewResult) -> str:
    return (
        f"Brewing {result.beverage_name}!\n"
        f"Command sent successfully.\nResponse: {result.response}"
    )


def format_beverages(beverages: dict[int, str]) -> str:
    lines = ["Available beverages:\n"]
    for recipe_id, name in beverages.items():
        lines.append(f"  {name} (ID 0x{recipe_id:02X})")
    lines.append(f"\n{len(beverages)} beverages ready to brew.")
    return "\n".join(lines)
