"""Configuration management for the De'Longhi MCP server."""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AylaSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DELONGHI_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    ayla_app_id: str = ""
    ayla_app_secret: str = ""
    ayla_auth_base_url: str = "https://user-field-eu.aylanetworks.com"
    ayla_ads_base_url: str = "https://ads-eu.aylanetworks.com"

    # Gigya SSO token (used by Coffee Link app instead of email/password)
    ayla_sso_token: SecretStr = SecretStr("")

    # Legacy email/password auth (alternative to SSO token)
    ayla_email: str = ""
    ayla_password: SecretStr = SecretStr("")

    def is_configured(self) -> bool:
        has_app_creds = bool(self.ayla_app_id and self.ayla_app_secret)
        has_auth = bool(
            self.ayla_sso_token.get_secret_value()
            or (self.ayla_email and self.ayla_password.get_secret_value())
        )
        return has_app_creds and has_auth
