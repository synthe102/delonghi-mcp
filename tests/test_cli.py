"""Tests for the Typer CLI."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from delonghi_mcp.api import BrewResult
from delonghi_mcp.cli import app
from delonghi_mcp.exceptions import DeLonghiMCPError
from delonghi_mcp.models import DeviceInfo, DeviceProperty
from delonghi_mcp.protocol import STATUS_PROPERTIES

runner = CliRunner()


@pytest.fixture
def mock_api() -> Iterator[MagicMock]:
    """Patch DeLonghiAPI so `async with DeLonghiAPI()` yields a mock instance."""
    api = MagicMock()
    api.list_devices = AsyncMock()
    api.get_machine_status = AsyncMock()
    api.get_all_properties = AsyncMock()
    api.power_on = AsyncMock()
    api.list_beverages = AsyncMock()
    api.brew = AsyncMock()

    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=api)
    context.__aexit__ = AsyncMock(return_value=None)

    with patch("delonghi_mcp.cli.DeLonghiAPI", return_value=context):
        yield api


def test_devices_prints_formatted_list(mock_api: MagicMock) -> None:
    mock_api.list_devices.return_value = [
        DeviceInfo(
            dsn="AC000W123456",
            device_id=42,
            product_name="DeLonghi Eletta Explore",
            model="ECAM550.65.S",
            connection_status="Online",
        )
    ]
    result = runner.invoke(app, ["devices"])
    assert result.exit_code == 0
    assert "AC000W123456" in result.output
    assert "DeLonghi Eletta Explore" in result.output
    assert "Auto-selected device: AC000W123456" in result.output


def test_devices_empty_list(mock_api: MagicMock) -> None:
    mock_api.list_devices.return_value = []
    result = runner.invoke(app, ["devices"])
    assert result.exit_code == 0
    assert "No devices found" in result.output


def test_status_formats_properties(mock_api: MagicMock) -> None:
    descaling_label = STATUS_PROPERTIES["d512_percentage_to_deca"]
    mock_api.get_machine_status.return_value = {
        descaling_label: DeviceProperty(
            name="d512_percentage_to_deca", value=42, direction="output"
        ),
    }
    result = runner.invoke(app, ["status", "--dsn", "AC000W123"])
    assert result.exit_code == 0
    assert "42%" in result.output
    mock_api.get_machine_status.assert_awaited_once_with("AC000W123")


def test_status_flags_descaling_overdue(mock_api: MagicMock) -> None:
    descaling_label = STATUS_PROPERTIES["d512_percentage_to_deca"]
    mock_api.get_machine_status.return_value = {
        descaling_label: DeviceProperty(
            name="d512_percentage_to_deca", value=120, direction="output"
        ),
    }
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "DESCALING OVERDUE" in result.output
    assert "20% past threshold" in result.output


def test_properties_split_input_output(mock_api: MagicMock) -> None:
    mock_api.get_all_properties.return_value = [
        DeviceProperty(name="app_device_status", value="RUN", direction="output"),
        DeviceProperty(name="app_data_request", value="", direction="input"),
    ]
    result = runner.invoke(app, ["properties"])
    assert result.exit_code == 0
    assert "Status properties" in result.output
    assert "Command properties" in result.output
    assert "app_device_status" in result.output
    assert "app_data_request" in result.output


def test_power_on(mock_api: MagicMock) -> None:
    mock_api.power_on.return_value = {"datapoint": {"value": "ok"}}
    result = runner.invoke(app, ["power-on"])
    assert result.exit_code == 0
    assert "Power-on command sent" in result.output


def test_beverages(mock_api: MagicMock) -> None:
    mock_api.list_beverages.return_value = {0x01: "espresso", 0x07: "cappuccino"}
    result = runner.invoke(app, ["beverages"])
    assert result.exit_code == 0
    assert "espresso (ID 0x01)" in result.output
    assert "cappuccino (ID 0x07)" in result.output
    assert "2 beverages ready to brew" in result.output


def test_brew_forwards_overrides(mock_api: MagicMock) -> None:
    mock_api.brew.return_value = BrewResult(
        beverage_name="espresso",
        recipe_id=0x01,
        response={"datapoint": {"value": "ok"}},
    )
    result = runner.invoke(
        app,
        [
            "brew",
            "espresso",
            "--coffee-ml",
            "40",
            "--intensity",
            "4",
        ],
    )
    assert result.exit_code == 0
    assert "Brewing espresso" in result.output
    mock_api.brew.assert_awaited_once_with(
        "espresso",
        None,
        coffee_quantity_ml=40,
        milk_quantity_ml=None,
        water_quantity_ml=None,
        intensity=4,
    )


def test_brew_unknown_beverage_exits_nonzero(mock_api: MagicMock) -> None:
    mock_api.brew.side_effect = ValueError("Unknown beverage 'flatwhitemocha'.")
    result = runner.invoke(app, ["brew", "flatwhitemocha"])
    assert result.exit_code == 1
    assert "ERROR" in result.output
    assert "Unknown beverage" in result.output


def test_delonghi_error_exits_nonzero(mock_api: MagicMock) -> None:
    mock_api.list_devices.side_effect = DeLonghiMCPError("Not authenticated")
    result = runner.invoke(app, ["devices"])
    assert result.exit_code == 1
    assert "ERROR" in result.output
    assert "Not authenticated" in result.output
