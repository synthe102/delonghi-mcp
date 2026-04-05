"""Integration tests for Ayla authentication against the real API.

Skipped unless DELONGHI_* credentials are present in env vars / .env.
Run with: uv run pytest -m integration -v
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from delonghi_mcp.ayla_client import AylaClient
from delonghi_mcp.config import AylaSettings
from delonghi_mcp.exceptions import AuthenticationError

pytestmark = pytest.mark.integration


@pytest.fixture
def real_settings() -> AylaSettings:
    settings = AylaSettings()
    if not (settings.ayla_app_id and settings.ayla_app_secret):
        pytest.skip("DELONGHI_AYLA_APP_ID / DELONGHI_AYLA_APP_SECRET not set")
    if not settings.ayla_sso_token.get_secret_value():
        pytest.skip("DELONGHI_AYLA_SSO_TOKEN not set")
    return settings


@pytest.fixture
def real_email_settings() -> AylaSettings:
    settings = AylaSettings()
    if not (settings.ayla_app_id and settings.ayla_app_secret):
        pytest.skip("DELONGHI_AYLA_APP_ID / DELONGHI_AYLA_APP_SECRET not set")
    if not (settings.email and settings.password.get_secret_value()):
        pytest.skip("DELONGHI_EMAIL / DELONGHI_PASSWORD not set")
    return settings


@pytest.fixture
def real_email_client(real_email_settings: AylaSettings, tmp_path: Path) -> AylaClient:
    return AylaClient(
        httpx.AsyncClient(),
        real_email_settings,
        token_file=tmp_path / ".ayla_token.json",
    )


@pytest.fixture
def real_client(real_settings: AylaSettings, tmp_path: Path) -> AylaClient:
    return AylaClient(
        httpx.AsyncClient(), real_settings, token_file=tmp_path / ".ayla_token.json"
    )


async def test_sso_auth_succeeds(real_client: AylaClient) -> None:
    auth = await real_client.authenticate()
    assert real_client.is_authenticated
    assert auth.access_token
    assert auth.refresh_token


async def test_wrong_app_id_raises(real_settings: AylaSettings, tmp_path: Path) -> None:
    bad = AylaSettings(
        ayla_app_id="bad-app-id",
        ayla_app_secret=real_settings.ayla_app_secret,
        ayla_sso_token=real_settings.ayla_sso_token,
    )
    client = AylaClient(httpx.AsyncClient(), bad, token_file=tmp_path / ".tok")

    with pytest.raises(AuthenticationError, match="app_id or app_secret"):
        await client.authenticate()


async def test_gigya_email_auth_succeeds(real_email_client: AylaClient) -> None:
    auth = await real_email_client.authenticate()
    assert real_email_client.is_authenticated
    assert auth.access_token
    assert auth.refresh_token


async def test_wrong_app_secret_raises(
    real_settings: AylaSettings, tmp_path: Path
) -> None:
    bad = AylaSettings(
        ayla_app_id=real_settings.ayla_app_id,
        ayla_app_secret="bad-app-secret",
        ayla_sso_token=real_settings.ayla_sso_token,
    )
    client = AylaClient(httpx.AsyncClient(), bad, token_file=tmp_path / ".tok")

    with pytest.raises(AuthenticationError, match="app_id or app_secret"):
        await client.authenticate()
