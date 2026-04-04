"""Tests for the binary protocol module."""

from __future__ import annotations

import base64
import struct

import pytest

from delonghi_mcp.protocol import (
    CAPTURED_BREW_PARAMS,
    QUANTITY_TYPES,
    build_brew_command,
    crc16_ccitt,
    extract_device_suffix,
    parse_stored_recipe,
    parse_tv_pairs,
    stored_to_brew_params,
)


def test_crc16_ccitt_known_recipe() -> None:
    """Verify CRC against known stored recipe data."""
    # Profile 1 espresso: last 2 bytes are CRC
    data = base64.b64decode("0BKm8AEBCAABACgbAQIEGQFnbg==")
    crc_stored = struct.unpack(">H", data[-2:])[0]
    crc_calc = crc16_ccitt(data[:-2])
    assert crc_calc == crc_stored


def test_crc16_ccitt_regular_recipe() -> None:
    data = base64.b64decode("0BCm8AECGQEbAQEAtAICL7A=")
    crc_stored = struct.unpack(">H", data[-2:])[0]
    crc_calc = crc16_ccitt(data[:-2])
    assert crc_calc == crc_stored


def test_parse_stored_recipe_espresso() -> None:
    profile_id, recipe_id, params = parse_stored_recipe(
        "0BKm8AEBCAABACgbAQIEGQFnbg=="
    )
    assert profile_id == 0x01
    assert recipe_id == 0x01  # espresso
    assert len(params) > 0


def test_parse_stored_recipe_regular() -> None:
    profile_id, recipe_id, params = parse_stored_recipe(
        "0BCm8AECGQEbAQEAtAICL7A="
    )
    assert profile_id == 0x01
    assert recipe_id == 0x02  # regular


def test_extract_device_suffix() -> None:
    # app_device_connected value: 69 D1 28 56 00 19 A7 A9
    suffix = extract_device_suffix("adEoVgAZp6k=")
    assert suffix == bytes([0x00, 0x19, 0xA7, 0xA9])


def test_build_brew_command_crc_valid() -> None:
    """Build a brew command and verify the CRC is correct."""
    recipe_params = bytes([0x08, 0x00, 0x01, 0x00, 0x28, 0x1B, 0x01, 0x02, 0x04, 0x19, 0x01])
    suffix = bytes([0x00, 0x19, 0xA7, 0xA9])
    timestamp = 1775315296

    cmd_b64 = build_brew_command(0x01, recipe_params, suffix, timestamp)
    cmd = base64.b64decode(cmd_b64)

    # Verify start marker
    assert cmd[0] == 0x0D

    # Verify length and CRC
    # Protocol total = length + 1 bytes. CRC is over bytes[0:length-1].
    n = cmd[1]
    crc_input = cmd[: n - 1]
    crc_stored = struct.unpack(">H", cmd[n - 1 : n + 1])[0]
    crc_calc = crc16_ccitt(crc_input)
    assert crc_calc == crc_stored

    # Verify timestamp — trailer starts after protocol part (length+1 bytes)
    trailer = cmd[n + 1 :]
    ts = struct.unpack(">I", trailer[:4])[0]
    assert ts == timestamp

    # Verify suffix
    assert trailer[4:] == suffix


def test_build_brew_command_reproduces_captured_espresso() -> None:
    """Verify we can reproduce the captured espresso brew command."""
    # Captured espresso command:
    # Protocol: 0D 13 83 F0 01 03 01 00 28 02 04 08 00 1B 01 27 01 06 [CRC: 35 3F]
    # Trailer: 69 D1 29 60 00 19 A7 A9

    # The recipe params in the brew command (bytes [6:18] of protocol):
    # 01 00 28 02 04 08 00 1B 01 27 01 06
    recipe_params = bytes([0x01, 0x00, 0x28, 0x02, 0x04, 0x08, 0x00, 0x1B, 0x01, 0x27, 0x01, 0x06])
    suffix = bytes([0x00, 0x19, 0xA7, 0xA9])
    timestamp = 1775315296  # 2026-04-04 15:08:16 UTC

    cmd_b64 = build_brew_command(0x01, recipe_params, suffix, timestamp)
    assert cmd_b64 == "DROD8AEDAQAoAgQIABsBJwEGNT9p0SlgABmnqQ=="


def test_build_brew_command_reproduces_captured_regular() -> None:
    """Verify we can reproduce the captured regular coffee brew command."""
    # Recipe params from captured command
    recipe_params = bytes([0x01, 0x00, 0xB4, 0x02, 0x02, 0x1B, 0x01, 0x27, 0x01, 0x06])
    suffix = bytes([0x00, 0x19, 0xA7, 0xA9])
    timestamp = 1775315400  # 2026-04-04 15:10:00 UTC

    cmd_b64 = build_brew_command(0x02, recipe_params, suffix, timestamp)
    assert cmd_b64 == "DRGD8AIDAQC0AgIbAScBBhKpadEpyAAZp6k="


# ---------------------------------------------------------------------------
# TV pair parsing and stored-to-brew conversion
# ---------------------------------------------------------------------------


def test_parse_tv_pairs_espresso() -> None:
    """Parse TV pairs from espresso stored params."""
    _, _, params = parse_stored_recipe("0BKm8AEBCAABACgbAQIEGQFnbg==")
    pairs = parse_tv_pairs(params)
    assert len(pairs) == 5
    assert pairs[0] == (0x08, b"\x00")
    assert pairs[1] == (0x01, b"\x00\x28")  # coffee size 40ml
    assert pairs[2] == (0x1B, b"\x01")
    assert pairs[3] == (0x02, b"\x04")
    assert pairs[4] == (0x19, b"\x01")


def test_stored_to_brew_params_espresso() -> None:
    """Conversion must match captured espresso brew params."""
    _, _, stored = parse_stored_recipe("0BKm8AEBCAABACgbAQIEGQFnbg==")
    assert stored_to_brew_params(stored) == CAPTURED_BREW_PARAMS[0x01]


def test_stored_to_brew_params_regular() -> None:
    """Conversion must match captured regular coffee brew params."""
    _, _, stored = parse_stored_recipe("0BCm8AECGQEbAQEAtAICL7A=")
    assert stored_to_brew_params(stored) == CAPTURED_BREW_PARAMS[0x02]


@pytest.mark.parametrize(
    "b64,expected_recipe_id",
    [
        ("0Bem8AEHCwIcAhkBAQBBGwECAwkA0340", 0x07),  # Cappuccino (milk drink)
        ("0BCm8AEQHAEZAQ8AlhsB3AU=", 0x10),  # Hot Water (no coffee)
        ("0BKm8AEWHAEZAQ8AlhsBDQEtxQ==", 0x16),  # Tea (has 0x0D type)
        ("0BOm8AEyGQEBACgPAFobAQIBvk0=", 0x32),  # Iced Americano
        ("0BOm8AFQG/8ZAQEAXw8BBAIBouM=", 0x50),  # Mug Americano
        ("0BCm8AF4GQEBAHgbAQIBcEs=", 0x78),  # Cold Brew Coffee
    ],
)
def test_stored_to_brew_params_various(b64: str, expected_recipe_id: int) -> None:
    """Conversion works for different beverage categories."""
    _, recipe_id, stored = parse_stored_recipe(b64)
    assert recipe_id == expected_recipe_id
    brew = stored_to_brew_params(stored)
    # Verify structure: ends with 0x06, contains 0x27=0x01, no 0x19
    assert brew[-1:] == b"\x06"
    assert b"\x27\x01" in brew
    pairs = parse_tv_pairs(brew[:-1])  # strip terminator
    types = [t for t, _ in pairs]
    assert 0x19 not in types
    assert 0x27 in types
    assert types == sorted(types)  # sorted ascending
