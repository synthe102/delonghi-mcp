"""Tests for configuration loading."""

from __future__ import annotations

from pydantic import SecretStr

from delonghi_mcp.config import AylaSettings


def test_ayla_settings_defaults() -> None:
    settings = AylaSettings(
        ayla_app_id="",
        ayla_app_secret="",
        ayla_sso_token=SecretStr(""),
        email="",
        password=SecretStr(""),
    )
    assert settings.ayla_auth_base_url == "https://user-field-eu.aylanetworks.com"
    assert settings.ayla_ads_base_url == "https://ads-eu.aylanetworks.com"
    assert not settings.is_configured()


def test_ayla_settings_configured_with_sso() -> None:
    settings = AylaSettings(
        ayla_app_id="app-id",
        ayla_app_secret="app-secret",
        ayla_sso_token=SecretStr("jwt-token"),
        email="",
        password=SecretStr(""),
    )
    assert settings.is_configured()


def test_ayla_settings_not_configured_without_token() -> None:
    settings = AylaSettings(
        ayla_app_id="app-id",
        ayla_app_secret="app-secret",
        ayla_sso_token=SecretStr(""),
        email="",
        password=SecretStr(""),
    )
    assert not settings.is_configured()


def test_ayla_settings_configured_with_email_password() -> None:
    settings = AylaSettings(
        ayla_app_id="app-id",
        ayla_app_secret="app-secret",
        ayla_sso_token=SecretStr(""),
        email="user@example.com",
        password=SecretStr("secret"),
    )
    assert settings.is_configured()


def test_ayla_settings_not_configured_email_only() -> None:
    settings = AylaSettings(
        ayla_app_id="app-id",
        ayla_app_secret="app-secret",
        ayla_sso_token=SecretStr(""),
        email="user@example.com",
        password=SecretStr(""),
    )
    assert not settings.is_configured()
