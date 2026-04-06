"""High-level async API for controlling a De'Longhi coffee machine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from delonghi_mcp.ayla_client import AylaClient
from delonghi_mcp.config import AylaSettings
from delonghi_mcp.exceptions import DeLonghiMCPError
from delonghi_mcp.models import DeviceInfo, DeviceProperty
from delonghi_mcp.protocol import (
    RECIPE_IDS,
    RECIPE_NAMES,
    STATUS_PROPERTIES,
    build_brew_command,
    build_connect_command,
    build_init_command,
    build_power_on_command,
    extract_device_suffix,
    override_brew_params,
    parse_stored_recipe,
    stored_to_brew_params,
)


@dataclass
class BrewResult:
    beverage_name: str
    recipe_id: int
    response: dict[str, Any]


def resolve_recipe_id(beverage: str) -> int | None:
    """Fuzzy-match a beverage name to a recipe ID."""
    normalized = beverage.lower().strip().replace("-", " ").replace("_", " ")
    if normalized in RECIPE_IDS:
        return RECIPE_IDS[normalized]
    for name, rid in RECIPE_IDS.items():
        if normalized in name or name in normalized:
            return rid
    return None


def _build_overrides(
    coffee_quantity_ml: int | None = None,
    milk_quantity_ml: int | None = None,
    water_quantity_ml: int | None = None,
    intensity: int | None = None,
) -> dict[int, int]:
    """Validate override parameters and return a type-code-to-value dict."""
    overrides: dict[int, int] = {}
    for param_val, type_code, label, lo, hi in [
        (coffee_quantity_ml, 0x01, "coffee_quantity_ml", 1, 999),
        (milk_quantity_ml, 0x09, "milk_quantity_ml", 1, 999),
        (water_quantity_ml, 0x0F, "water_quantity_ml", 1, 999),
        (intensity, 0x02, "intensity", 1, 5),
    ]:
        if param_val is not None:
            if not (lo <= param_val <= hi):
                raise ValueError(
                    f"{label} must be between {lo} and {hi}, got {param_val}"
                )
            overrides[type_code] = param_val
    return overrides


class DeLonghiAPI:
    """High-level async API for controlling a De'Longhi coffee machine.

    Owns the httpx client lifecycle and AylaClient. Use as an async context
    manager for automatic resource cleanup, or pass a pre-built client via
    ``_client`` for testing.
    """

    def __init__(
        self,
        settings: AylaSettings | None = None,
        *,
        _client: AylaClient | None = None,
    ) -> None:
        self._settings = settings or AylaSettings()
        self._http_client: httpx.AsyncClient | None = None
        self._client: AylaClient | None = _client
        self._selected_dsn: str | None = None
        self._device_suffix: bytes | None = None
        self._recipe_cache: dict[int, bytes] | None = None

    async def __aenter__(self) -> DeLonghiAPI:
        self._http_client = httpx.AsyncClient(timeout=30.0)
        self._client = AylaClient(self._http_client, self._settings)
        if self._settings.is_configured() or self._client.has_saved_credentials():
            try:
                await self._client.authenticate()
            except Exception:
                pass  # Methods will re-attempt via _ensure_auth
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        self._client = None

    def _require_client(self) -> AylaClient:
        if self._client is None:
            raise RuntimeError(
                "DeLonghiAPI must be used as an async context manager "
                "or constructed with _client for testing."
            )
        return self._client

    # -- Device management ---------------------------------------------------

    @property
    def selected_dsn(self) -> str | None:
        return self._selected_dsn

    @selected_dsn.setter
    def selected_dsn(self, dsn: str | None) -> None:
        self._selected_dsn = dsn
        self._device_suffix = None
        self._recipe_cache = None

    async def list_devices(self) -> list[DeviceInfo]:
        """List all connected devices. Auto-selects if exactly one."""
        devices = await self._require_client().list_devices()
        if len(devices) == 1:
            self._selected_dsn = devices[0].dsn
        return devices

    # -- Connection ----------------------------------------------------------

    async def ensure_device_suffix(self, dsn: str | None = None) -> bytes:
        """Read and cache the 4-byte device suffix from ``app_device_connected``."""
        if self._device_suffix:
            return self._device_suffix
        dsn = dsn or self._selected_dsn
        prop = await self._require_client().get_property(
            "app_device_connected", dsn
        )
        if not prop.value:
            raise DeLonghiMCPError("Cannot read app_device_connected property.")
        self._device_suffix = extract_device_suffix(prop.value)
        return self._device_suffix

    async def connect(self, dsn: str | None = None) -> None:
        """Establish connection with the machine (handshake + init)."""
        dsn = dsn or self._selected_dsn
        suffix = await self.ensure_device_suffix(dsn)
        client = self._require_client()
        await client.set_property(
            "app_device_connected", build_connect_command(suffix), dsn
        )
        await client.set_property(
            "app_data_request", build_init_command(suffix), dsn
        )

    # -- Power ---------------------------------------------------------------

    async def power_on(self, dsn: str | None = None) -> dict[str, Any]:
        """Send power-on command. Returns the Ayla API response dict."""
        dsn = dsn or self._selected_dsn
        await self.connect(dsn)
        suffix = await self.ensure_device_suffix(dsn)
        command = build_power_on_command(suffix)
        return await self._require_client().set_property(
            "app_data_request", command, dsn
        )

    # -- Properties / Status -------------------------------------------------

    async def get_all_properties(
        self, dsn: str | None = None
    ) -> list[DeviceProperty]:
        """Fetch all device properties."""
        dsn = dsn or self._selected_dsn
        return await self._require_client().get_device_properties(dsn)

    async def get_machine_status(
        self, dsn: str | None = None
    ) -> dict[str, DeviceProperty | None]:
        """Fetch status properties, keyed by human-readable label."""
        dsn = dsn or self._selected_dsn
        all_props = await self._require_client().get_device_properties(dsn)
        props_by_name = {p.name: p for p in all_props}
        return {
            label: props_by_name.get(prop_name)
            for prop_name, label in STATUS_PROPERTIES.items()
        }

    # -- Recipes / Brewing ---------------------------------------------------

    async def get_brew_params(self, dsn: str | None = None) -> dict[int, bytes]:
        """Fetch and cache brew parameters for all stored recipes."""
        if self._recipe_cache is not None:
            return self._recipe_cache

        dsn = dsn or self._selected_dsn
        all_props = await self._require_client().get_device_properties(dsn)
        cache: dict[int, bytes] = {}
        for prop in all_props:
            if not (
                prop.name.startswith("d") and "_rec_1_" in prop.name and prop.value
            ):
                continue
            try:
                _profile_id, recipe_id, stored_params = parse_stored_recipe(
                    prop.value
                )
                cache[recipe_id] = stored_to_brew_params(stored_params)
            except (ValueError, IndexError):
                continue

        self._recipe_cache = cache
        return cache

    async def list_beverages(self, dsn: str | None = None) -> dict[int, str]:
        """Return available beverages as ``{recipe_id: name}``."""
        brew_params = await self.get_brew_params(dsn)
        return {
            rid: RECIPE_NAMES.get(rid, f"Unknown (0x{rid:02X})")
            for rid in sorted(brew_params)
        }

    async def brew(
        self,
        beverage: str,
        dsn: str | None = None,
        coffee_quantity_ml: int | None = None,
        milk_quantity_ml: int | None = None,
        water_quantity_ml: int | None = None,
        intensity: int | None = None,
    ) -> BrewResult:
        """Brew a beverage with optional parameter overrides."""
        recipe_id = resolve_recipe_id(beverage)
        if recipe_id is None:
            available = sorted(RECIPE_IDS.keys())
            raise ValueError(
                f"Unknown beverage '{beverage}'. Available: {available}"
            )

        beverage_name = RECIPE_NAMES.get(recipe_id, beverage)
        dsn = dsn or self._selected_dsn

        brew_params = await self.get_brew_params(dsn)
        if recipe_id not in brew_params:
            available = {
                rid: RECIPE_NAMES.get(rid, f"ID 0x{rid:02X}")
                for rid in sorted(brew_params)
            }
            raise ValueError(
                f"'{beverage_name}' recipe not found on the machine. "
                f"Available: {available}"
            )

        overrides = _build_overrides(
            coffee_quantity_ml, milk_quantity_ml, water_quantity_ml, intensity
        )
        recipe_bytes = brew_params[recipe_id]
        if overrides:
            recipe_bytes = override_brew_params(recipe_bytes, overrides)

        await self.connect(dsn)
        suffix = await self.ensure_device_suffix(dsn)
        command = build_brew_command(recipe_id, recipe_bytes, suffix)
        response = await self._require_client().set_property(
            "app_data_request", command, dsn
        )

        return BrewResult(
            beverage_name=beverage_name,
            recipe_id=recipe_id,
            response=response,
        )
