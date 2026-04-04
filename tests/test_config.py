"""Tests for configuration loading."""

from __future__ import annotations

from delonghi_mcp.config import AylaSettings


def test_ayla_settings_defaults() -> None:
    settings = AylaSettings(
        ayla_email="",
        ayla_password="",
        ayla_app_id="",
        ayla_app_secret="",
    )
    assert settings.ayla_auth_base_url == "https://user-field-eu.aylanetworks.com"
    assert settings.ayla_ads_base_url == "https://ads-eu.aylanetworks.com"
    assert not settings.is_configured()


def test_ayla_settings_configured_with_sso() -> None:
    settings = AylaSettings(
        ayla_app_id="app-id",
        ayla_app_secret="app-secret",
        ayla_sso_token="jwt-token",
    )
    assert settings.is_configured()


def test_ayla_settings_configured_with_password() -> None:
    settings = AylaSettings(
        ayla_email="test@example.com",
        ayla_password="pass",
        ayla_app_id="app-id",
        ayla_app_secret="app-secret",
    )
    assert settings.is_configured()


def test_ayla_settings_not_configured_without_auth() -> None:
    settings = AylaSettings(
        ayla_app_id="app-id",
        ayla_app_secret="app-secret",
    )
    assert not settings.is_configured()
