"""Pydantic models for the De'Longhi MCP server."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuthState(BaseModel):
    access_token: str
    refresh_token: str
    expires_at: datetime
    role: str = ""


class DeviceInfo(BaseModel):
    dsn: str
    device_id: int
    product_name: str
    model: str
    oem_model: str = ""
    mac: str | None = None
    lan_ip: str | None = None
    connection_status: str = "unknown"
    connected_at: str | None = None


class DeviceProperty(BaseModel):
    name: str
    value: Any = None
    read_only: bool = False
    type: str = "string"
    direction: str = ""
    updated_at: str | None = None
