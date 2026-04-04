"""Binary protocol for De'Longhi Eletta Explore (DL-striker-cb).

Packet format:
    [0x0D] [len] [payload] [CRC16] [4B timestamp BE] [4B device suffix BE]

Where:
    - len = len(payload) + 3 (includes len byte itself + 2 CRC bytes)
    - CRC16 = CRC-16/CCITT (init=0x1D0F) over bytes [0:len-1]
    - timestamp = unix timestamp (uint32 big-endian)
    - device suffix = constant per-device identifier (from app_device_connected)
"""

from __future__ import annotations

import base64
import struct
import time


def crc16_ccitt(data: bytes, init: int = 0x1D0F) -> int:
    """Calculate CRC-16/CCITT checksum."""
    crc = init
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc = crc << 1
            crc &= 0xFFFF
    return crc


def _build_packet(
    payload: bytes,
    device_suffix: bytes,
    timestamp: int | None = None,
) -> str:
    """Build a base64-encoded packet with CRC, timestamp, and device suffix."""
    if timestamp is None:
        timestamp = int(time.time())

    length = len(payload) + 3
    crc_input = bytes([0x0D, length]) + payload
    crc = crc16_ccitt(crc_input)
    packet = crc_input + struct.pack(">H", crc) + struct.pack(">I", timestamp) + device_suffix
    return base64.b64encode(packet).decode("ascii")


def build_brew_command(
    recipe_id: int,
    recipe_params: bytes,
    device_suffix: bytes,
    timestamp: int | None = None,
) -> str:
    """Build a base64-encoded brew command packet."""
    payload = bytes([0x83, 0xF0, recipe_id, 0x03]) + recipe_params
    return _build_packet(payload, device_suffix, timestamp)


def build_init_command(
    device_suffix: bytes, timestamp: int | None = None
) -> str:
    """Build the initialization command (0xE8F0) sent before brew commands."""
    payload = bytes([0xE8, 0xF0, 0x00, 0xED, 0x7C])
    return _build_packet(payload, device_suffix, timestamp)


def build_connect_command(device_suffix: bytes, timestamp: int | None = None) -> str:
    """Build a connection handshake for app_device_connected."""
    if timestamp is None:
        timestamp = int(time.time())
    packet = struct.pack(">I", timestamp) + device_suffix
    return base64.b64encode(packet).decode("ascii")


def parse_stored_recipe(recipe_b64: str) -> tuple[int, int, bytes]:
    """Parse a stored per-profile recipe (d059-d231 properties).

    Returns:
        (profile_id, recipe_id, recipe_params)
    """
    data = base64.b64decode(recipe_b64)
    if data[0] != 0xD0:
        raise ValueError(f"Invalid recipe start marker: 0x{data[0]:02X}")
    return data[4], data[5], data[6:-2]


def extract_device_suffix(app_device_connected_b64: str) -> bytes:
    """Extract the 4-byte device suffix from app_device_connected."""
    return base64.b64decode(app_device_connected_b64)[-4:]


RECIPE_NAMES: dict[int, str] = {
    0x01: "Espresso",
    0x02: "Regular Coffee",
    0x03: "Long Coffee",
    0x04: "2x Espresso",
    0x05: "Doppio+",
    0x06: "Americano",
    0x07: "Cappuccino",
    0x08: "Latte Macchiato",
    0x09: "Caffe Latte",
    0x0A: "Flat White",
    0x0B: "Espresso Macchiato",
    0x0C: "Hot Milk",
    0x0D: "Cappuccino Doppio+",
    0x0F: "Cappuccino Reverse",
    0x10: "Hot Water",
    0x16: "Tea",
    0x17: "Coffee Pot",
    0x18: "Cortado",
    0x1B: "Brew Over Ice",
    0x32: "Iced Americano",
    0x33: "Iced Cappuccino",
    0x34: "Iced Latte Macchiato",
    0x35: "Iced Cappuccino Mix",
    0x36: "Iced Flat White",
    0x37: "Iced Cold Milk",
    0x38: "Iced Caffe Latte",
    0x39: "Over Ice Espresso",
}

RECIPE_IDS: dict[str, int] = {v.lower(): k for k, v in RECIPE_NAMES.items()}

# Captured brew command params (from Coffee Link app MITM).
# The stored recipe params use a different byte ordering and cannot be sent directly.
CAPTURED_BREW_PARAMS: dict[int, bytes] = {
    0x01: bytes([0x01, 0x00, 0x28, 0x02, 0x04, 0x08, 0x00, 0x1B, 0x01, 0x27, 0x01, 0x06]),  # Espresso
    0x02: bytes([0x01, 0x00, 0xB4, 0x02, 0x02, 0x1B, 0x01, 0x27, 0x01, 0x06]),  # Regular Coffee
}

STATUS_PROPERTIES: dict[str, str] = {
    "app_device_status": "Machine Status",
    "d510_ground_cnt_percentage": "Grounds Container (%)",
    "d512_percentage_to_deca": "Descaling Progress (%)",
    "d513_percentage_usage_fltr": "Filter Usage (%)",
    "d550_water_calc_qty": "Water Calc Quantity",
    "d551_cnt_coffee_fondi": "Coffee Grounds Count",
    "d556_water_hardness": "Water Hardness",
    "d558_bev_cnt_desc_on": "Beverages Since Descale",
    "d701_tot_bev_b": "Total Beverages",
    "d704_tot_bev_espressi": "Total Espressos",
    "d706_tot_id2_coffee": "Total Coffees",
    "d710_tot_id7_capp": "Total Cappuccinos",
}
