"""Typer CLI for controlling a De'Longhi coffee machine."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable
from typing import Annotated, TypeVar

import typer

from delonghi_mcp.api import DeLonghiAPI
from delonghi_mcp.exceptions import DeLonghiMCPError
from delonghi_mcp.formatting import (
    beverages_to_json_payload,
    format_beverages,
    format_brew_result,
    format_devices,
    format_power_on,
    format_properties,
    format_status,
    properties_to_json_payload,
    status_to_json_payload,
    to_json,
)

app = typer.Typer(
    name="delonghi",
    help="Control a De'Longhi coffee machine from the shell.",
    no_args_is_help=True,
    add_completion=False,
)

T = TypeVar("T")

DsnOption = Annotated[
    str | None,
    typer.Option("--dsn", help="Device serial number. Uses auto-selected device if omitted."),
]

JsonOption = Annotated[
    bool,
    typer.Option("--json", help="Emit JSON to stdout; errors become JSON on stderr."),
]


def _run(coro: Awaitable[T], json_output: bool = False) -> T:
    try:
        return asyncio.run(coro)
    except (DeLonghiMCPError, ValueError) as e:
        if json_output:
            typer.echo(json.dumps({"error": str(e)}), err=True)
        else:
            typer.echo(f"ERROR: {e}", err=True)
        raise typer.Exit(code=1) from e


async def _prime_device_cache(api: DeLonghiAPI, dsn: str | None) -> None:
    """Populate the Ayla device cache so per-command DSN lookups succeed.

    Each CLI invocation is a fresh process, so the AylaClient device cache
    (and ``selected_dsn`` auto-selection) starts empty. Running
    ``list_devices`` here primes both.
    """
    if dsn is None and api.selected_dsn is None:
        await api.list_devices()


@app.command()
def devices(json_output: JsonOption = False) -> None:
    """List all De'Longhi coffee machines on the account."""

    async def _impl() -> str:
        async with DeLonghiAPI() as api:
            data = await api.list_devices()
            return to_json(data) if json_output else format_devices(data)

    typer.echo(_run(_impl(), json_output))


@app.command("power-on")
def power_on(dsn: DsnOption = None, json_output: JsonOption = False) -> None:
    """Wake the coffee machine from standby."""

    async def _impl() -> str:
        async with DeLonghiAPI() as api:
            await _prime_device_cache(api, dsn)
            data = await api.power_on(dsn)
            return to_json(data) if json_output else format_power_on(data)

    typer.echo(_run(_impl(), json_output))


@app.command()
def status(dsn: DsnOption = None, json_output: JsonOption = False) -> None:
    """Show the machine's current status."""

    async def _impl() -> str:
        async with DeLonghiAPI() as api:
            await _prime_device_cache(api, dsn)
            data = await api.get_machine_status(dsn)
            if json_output:
                return to_json(status_to_json_payload(data))
            return format_status(data)

    typer.echo(_run(_impl(), json_output))


@app.command()
def properties(dsn: DsnOption = None, json_output: JsonOption = False) -> None:
    """Dump every property the machine exposes."""

    async def _impl() -> str:
        async with DeLonghiAPI() as api:
            await _prime_device_cache(api, dsn)
            data = await api.get_all_properties(dsn)
            if json_output:
                return to_json(properties_to_json_payload(data))
            return format_properties(data)

    typer.echo(_run(_impl(), json_output))


@app.command()
def beverages(dsn: DsnOption = None, json_output: JsonOption = False) -> None:
    """List beverages available on the machine."""

    async def _impl() -> str:
        async with DeLonghiAPI() as api:
            await _prime_device_cache(api, dsn)
            data = await api.list_beverages(dsn)
            if json_output:
                return to_json(beverages_to_json_payload(data))
            return format_beverages(data)

    typer.echo(_run(_impl(), json_output))


@app.command()
def brew(
    beverage: Annotated[str, typer.Argument(help="Beverage name, e.g. 'espresso'.")],
    dsn: DsnOption = None,
    coffee_ml: Annotated[
        int | None,
        typer.Option("--coffee-ml", help="Coffee amount in ml (1-999)."),
    ] = None,
    milk_ml: Annotated[
        int | None,
        typer.Option("--milk-ml", help="Milk amount in ml (1-999)."),
    ] = None,
    water_ml: Annotated[
        int | None,
        typer.Option("--water-ml", help="Water amount in ml (1-999)."),
    ] = None,
    intensity: Annotated[
        int | None,
        typer.Option("--intensity", help="Coffee strength from 1 (mild) to 5 (extra strong)."),
    ] = None,
    json_output: JsonOption = False,
) -> None:
    """Brew a beverage, optionally overriding recipe parameters."""

    async def _impl() -> str:
        async with DeLonghiAPI() as api:
            await _prime_device_cache(api, dsn)
            result = await api.brew(
                beverage,
                dsn,
                coffee_quantity_ml=coffee_ml,
                milk_quantity_ml=milk_ml,
                water_quantity_ml=water_ml,
                intensity=intensity,
            )
            return to_json(result) if json_output else format_brew_result(result)

    typer.echo(_run(_impl(), json_output))


if __name__ == "__main__":
    app()
