"""Tests for the high-level DeLonghiAPI."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from delonghi_mcp.api import DeLonghiAPI, resolve_recipe_id
from delonghi_mcp.models import DeviceProperty
from delonghi_mcp.protocol import CAPTURED_BREW_PARAMS


def test_resolve_recipe_id_exact() -> None:
    assert resolve_recipe_id("espresso") == 0x01
    assert resolve_recipe_id("regular coffee") == 0x02
    assert resolve_recipe_id("cappuccino") == 0x07


def test_resolve_recipe_id_case_insensitive() -> None:
    assert resolve_recipe_id("Espresso") == 0x01
    assert resolve_recipe_id("CAPPUCCINO") == 0x07
    assert resolve_recipe_id("Flat White") == 0x0A


def test_resolve_recipe_id_fuzzy() -> None:
    assert resolve_recipe_id("latte-macchiato") == 0x08
    assert resolve_recipe_id("latte_macchiato") == 0x08
    assert resolve_recipe_id("caffe latte") == 0x09


def test_resolve_recipe_id_partial() -> None:
    assert resolve_recipe_id("espresso") == 0x01
    assert resolve_recipe_id("americano") == 0x06


def test_resolve_recipe_id_not_found() -> None:
    assert resolve_recipe_id("mocha") is None
    assert resolve_recipe_id("xyz") is None


@pytest.mark.asyncio
async def test_get_brew_params_from_properties() -> None:
    """get_brew_params reads recipe properties and converts to brew params."""
    mock_client = MagicMock()
    mock_client.get_device_properties = AsyncMock(
        return_value=[
            DeviceProperty(
                name="d059_rec_1_espresso",
                value="0BKm8AEBCAABACgbAQIEGQFnbg==",
                direction="output",
            ),
            DeviceProperty(
                name="d060_rec_1_regular",
                value="0BCm8AECGQEbAQEAtAICL7A=",
                direction="output",
            ),
            DeviceProperty(name="app_device_status", value="RUN", direction="output"),
        ]
    )

    api = DeLonghiAPI(settings=MagicMock(), _client=mock_client)
    brew_params = await api.get_brew_params()

    assert brew_params[0x01] == CAPTURED_BREW_PARAMS[0x01]
    assert brew_params[0x02] == CAPTURED_BREW_PARAMS[0x02]
    assert api._recipe_cache is not None


@pytest.mark.asyncio
async def test_get_brew_params_caches() -> None:
    """get_brew_params returns cached results on subsequent calls."""
    mock_client = MagicMock()
    mock_client.get_device_properties = AsyncMock(
        return_value=[
            DeviceProperty(
                name="d059_rec_1_espresso",
                value="0BKm8AEBCAABACgbAQIEGQFnbg==",
                direction="output",
            ),
        ]
    )

    api = DeLonghiAPI(settings=MagicMock(), _client=mock_client)
    await api.get_brew_params()
    await api.get_brew_params()

    mock_client.get_device_properties.assert_called_once()
