"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from pydantic import SecretStr

from delonghi_mcp.ayla_client import AylaClient
from delonghi_mcp.config import AylaSettings


@pytest.fixture
def ayla_settings() -> AylaSettings:
    return AylaSettings(
        ayla_email="test@example.com",
        ayla_password=SecretStr("testpass"),
        ayla_app_id="test-app-id",
        ayla_app_secret="test-app-secret",
        ayla_auth_base_url="https://auth.test.example.com",
        ayla_ads_base_url="https://ads.test.example.com",
    )


@pytest.fixture
def http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient()


@pytest.fixture
def ayla_client(
    http_client: httpx.AsyncClient, ayla_settings: AylaSettings, tmp_path: Path
) -> AylaClient:
    # Use a non-existent token file so tests don't pick up real tokens
    return AylaClient(
        http_client, ayla_settings, token_file=tmp_path / ".ayla_token.json"
    )


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    return tmp_path
