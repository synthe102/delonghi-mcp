"""Async client for the Ayla Networks IoT cloud API."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from delonghi_mcp.config import AylaSettings
from delonghi_mcp.exceptions import (
    AuthenticationError,
    DeviceNotFoundError,
    NotAuthenticatedError,
    PropertyNotFoundError,
)
from delonghi_mcp.models import AuthState, DeviceInfo, DeviceProperty

_TOKEN_FILE = Path(__file__).resolve().parent.parent.parent / ".ayla_token.json"


class AylaClient:
    def __init__(
        self,
        http_client: httpx.AsyncClient,
        settings: AylaSettings,
        token_file: Path = _TOKEN_FILE,
    ):
        self._http = http_client
        self._settings = settings
        self._auth: AuthState | None = None
        self._devices: list[DeviceInfo] = []
        self._token_file = token_file

    @property
    def is_authenticated(self) -> bool:
        return self._auth is not None

    @property
    def auth_state(self) -> AuthState | None:
        return self._auth

    def has_saved_credentials(self) -> bool:
        """Check if a persisted refresh token exists on disk."""
        return self._load_refresh_token() is not None

    def _save_refresh_token(self) -> None:
        if not self._auth:
            return
        try:
            self._token_file.write_text(
                json.dumps({"refresh_token": self._auth.refresh_token})
            )
        except OSError:
            pass

    def _load_refresh_token(self) -> str | None:
        try:
            data = json.loads(self._token_file.read_text())
            return data.get("refresh_token")
        except (OSError, json.JSONDecodeError, KeyError):
            return None

    def _parse_auth_response(
        self, data: dict[str, Any], fallback_role: str = ""
    ) -> AuthState:
        self._auth = AuthState(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=datetime.now(UTC) + timedelta(hours=24),
            role=data.get("role", fallback_role),
        )
        self._save_refresh_token()
        return self._auth

    async def authenticate(self) -> AuthState:
        """Authenticate with Ayla IoT cloud.

        Tries in order: persisted refresh token, then SSO token.
        """
        saved_token = self._load_refresh_token()
        if saved_token:
            try:
                self._auth = AuthState(
                    access_token="",
                    refresh_token=saved_token,
                    expires_at=datetime.now(UTC),
                    role="",
                )
                return await self.refresh_token()
            except AuthenticationError:
                self._auth = None

        sso_token = self._settings.ayla_sso_token.get_secret_value()
        if sso_token:
            return await self._authenticate_sso(sso_token)

        raise AuthenticationError(
            "No SSO token configured and no saved refresh token. "
            "Set DELONGHI_AYLA_SSO_TOKEN in .env."
        )

    async def _authenticate_sso(self, token: str) -> AuthState:
        url = f"{self._settings.ayla_auth_base_url}/api/v1/token_sign_in"
        payload = {
            "app_id": self._settings.ayla_app_id,
            "app_secret": self._settings.ayla_app_secret,
            "token": token,
        }

        resp = await self._http.post(url, json=payload)
        if resp.status_code in (401, 403):
            raise AuthenticationError(
                "SSO token rejected. The token may have expired — "
                "re-open the Coffee Link app with the MITM proxy to capture a fresh one."
            )
        if resp.status_code == 404:
            raise AuthenticationError(
                "Invalid app_id or app_secret. "
                "See docs/reverse-engineering-guide.md to obtain correct values."
            )
        if resp.status_code != 200:
            raise AuthenticationError(
                f"SSO authentication failed with status {resp.status_code}: {resp.text}"
            )
        return self._parse_auth_response(resp.json())

    async def refresh_token(self) -> AuthState:
        if not self._auth:
            raise NotAuthenticatedError("No active session to refresh.")

        url = f"{self._settings.ayla_auth_base_url}/users/refresh_token.json"
        payload = {"user": {"refresh_token": self._auth.refresh_token}}

        resp = await self._http.post(url, json=payload)
        if resp.status_code != 200:
            self._auth = None
            raise AuthenticationError("Token refresh failed. Please re-authenticate.")

        return self._parse_auth_response(resp.json(), fallback_role=self._auth.role)

    async def _ensure_auth(self) -> None:
        if not self._auth:
            if self._settings.is_configured() or self.has_saved_credentials():
                await self.authenticate()
            else:
                raise NotAuthenticatedError(
                    "Not authenticated and no credentials configured."
                )
        assert self._auth is not None
        if self._auth.expires_at - datetime.now(UTC) < timedelta(seconds=60):
            await self.refresh_token()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        await self._ensure_auth()
        assert self._auth is not None

        url = f"{self._settings.ayla_ads_base_url}{path}"
        headers = {"Authorization": f"auth_token {self._auth.access_token}"}

        resp = await self._http.request(method, url, headers=headers, **kwargs)

        if resp.status_code == 401:
            await self.refresh_token()
            assert self._auth is not None
            headers["Authorization"] = f"auth_token {self._auth.access_token}"
            resp = await self._http.request(method, url, headers=headers, **kwargs)

        return resp

    async def list_devices(self) -> list[DeviceInfo]:
        resp = await self._request("GET", "/apiv1/devices.json")
        resp.raise_for_status()

        devices = []
        for item in resp.json():
            d = item.get("device", item)
            devices.append(
                DeviceInfo(
                    dsn=d["dsn"],
                    device_id=d.get("id", 0),
                    product_name=d.get("product_name", ""),
                    model=d.get("model", ""),
                    oem_model=d.get("oem_model", ""),
                    mac=d.get("mac"),
                    lan_ip=d.get("lan_ip"),
                    connection_status=d.get("connection_status", "unknown"),
                    connected_at=d.get("connected_at"),
                )
            )

        self._devices = devices
        return devices

    def _resolve_dsn(self, dsn: str | None) -> str:
        if dsn:
            return dsn
        if len(self._devices) == 1:
            return self._devices[0].dsn
        if not self._devices:
            raise DeviceNotFoundError("No devices cached. Call 'list_devices' first.")
        raise DeviceNotFoundError(
            f"Multiple devices found ({len(self._devices)}). "
            "Specify a DSN. Available: " + ", ".join(d.dsn for d in self._devices)
        )

    @staticmethod
    def _parse_property(p: dict[str, Any]) -> DeviceProperty:
        direction = p.get("direction", "")
        return DeviceProperty(
            name=p["name"],
            value=p.get("value"),
            read_only=direction == "output",
            type=p.get("base_type", "string"),
            direction=direction,
            updated_at=p.get("data_updated_at"),
        )

    async def get_device_properties(
        self, dsn: str | None = None
    ) -> list[DeviceProperty]:
        dsn = self._resolve_dsn(dsn)
        resp = await self._request("GET", f"/apiv1/dsns/{dsn}/properties.json")
        resp.raise_for_status()
        return [
            self._parse_property(item.get("property", item)) for item in resp.json()
        ]

    async def get_property(
        self, property_name: str, dsn: str | None = None
    ) -> DeviceProperty:
        dsn = self._resolve_dsn(dsn)
        resp = await self._request(
            "GET", f"/apiv1/dsns/{dsn}/properties/{property_name}.json"
        )
        if resp.status_code == 404:
            raise PropertyNotFoundError(
                f"Property '{property_name}' not found on device {dsn}."
            )
        resp.raise_for_status()

        data = resp.json()
        return self._parse_property(data.get("property", data))

    async def set_property(
        self, property_name: str, value: Any, dsn: str | None = None
    ) -> dict[str, Any]:
        dsn = self._resolve_dsn(dsn)
        resp = await self._request(
            "POST",
            f"/apiv1/dsns/{dsn}/properties/{property_name}/datapoints.json",
            json={"datapoint": {"value": value}},
        )
        if resp.status_code == 404:
            raise PropertyNotFoundError(
                f"Property '{property_name}' not found on device {dsn}."
            )
        resp.raise_for_status()
        return resp.json()
