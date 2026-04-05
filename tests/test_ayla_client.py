"""Tests for the Ayla IoT API client."""

from __future__ import annotations

import pathlib

import httpx
import pytest
import respx
from httpx import Response
from pydantic import SecretStr

from delonghi_mcp.ayla_client import AylaClient
from delonghi_mcp.config import AylaSettings
from delonghi_mcp.exceptions import (
    AuthenticationError,
    DeviceNotFoundError,
    NotAuthenticatedError,
    PropertyNotFoundError,
)


@pytest.mark.asyncio
@respx.mock
async def test_authenticate_sso_success(ayla_client: AylaClient) -> None:
    respx.post("https://auth.test.example.com/api/v1/token_sign_in").mock(
        return_value=Response(
            200,
            json={
                "access_token": "tok_123",
                "refresh_token": "ref_456",
                "role": "EndUser",
            },
        )
    )

    auth = await ayla_client.authenticate()
    assert auth.access_token == "tok_123"
    assert auth.refresh_token == "ref_456"
    assert auth.role == "EndUser"
    assert ayla_client.is_authenticated


@pytest.mark.asyncio
@respx.mock
async def test_authenticate_sso_expired(ayla_client: AylaClient) -> None:
    respx.post("https://auth.test.example.com/api/v1/token_sign_in").mock(
        return_value=Response(401, json={"error": "unauthorized"})
    )

    with pytest.raises(AuthenticationError, match="SSO token rejected"):
        await ayla_client.authenticate()


@pytest.mark.asyncio
@respx.mock
async def test_authenticate_invalid_app_id(ayla_client: AylaClient) -> None:
    respx.post("https://auth.test.example.com/api/v1/token_sign_in").mock(
        return_value=Response(404, json={"error": "not found"})
    )

    with pytest.raises(AuthenticationError, match="app_id or app_secret"):
        await ayla_client.authenticate()


@pytest.mark.asyncio
async def test_not_authenticated_raises(tmp_path: pathlib.Path) -> None:
    """A client with no credentials raises NotAuthenticatedError."""
    settings = AylaSettings(
        ayla_app_id="", ayla_app_secret="", ayla_sso_token=SecretStr("")
    )
    client = AylaClient(
        httpx.AsyncClient(), settings, token_file=tmp_path / ".ayla_token.json"
    )
    with pytest.raises(NotAuthenticatedError):
        await client.list_devices()


@pytest.mark.asyncio
@respx.mock
async def test_list_devices(ayla_client: AylaClient) -> None:
    # Authenticate first
    respx.post("https://auth.test.example.com/api/v1/token_sign_in").mock(
        return_value=Response(
            200,
            json={"access_token": "tok", "refresh_token": "ref"},
        )
    )
    await ayla_client.authenticate()

    respx.get("https://ads.test.example.com/apiv1/devices.json").mock(
        return_value=Response(
            200,
            json=[
                {
                    "device": {
                        "dsn": "DSN001",
                        "id": 42,
                        "product_name": "Eletta Explore",
                        "model": "ECAM450.55.G",
                        "oem_model": "ECAM450",
                        "mac": "AA:BB:CC:DD:EE:FF",
                        "lan_ip": "192.168.1.50",
                        "connection_status": "Online",
                        "connected_at": "2026-04-04T10:00:00Z",
                    }
                }
            ],
        )
    )

    devices = await ayla_client.list_devices()
    assert len(devices) == 1
    assert devices[0].dsn == "DSN001"
    assert devices[0].product_name == "Eletta Explore"
    assert devices[0].connection_status == "Online"


@pytest.mark.asyncio
@respx.mock
async def test_get_device_properties(ayla_client: AylaClient) -> None:
    respx.post("https://auth.test.example.com/api/v1/token_sign_in").mock(
        return_value=Response(200, json={"access_token": "tok", "refresh_token": "ref"})
    )
    await ayla_client.authenticate()

    respx.get("https://ads.test.example.com/apiv1/dsns/DSN001/properties.json").mock(
        return_value=Response(
            200,
            json=[
                {
                    "property": {
                        "name": "POWER",
                        "value": 1,
                        "base_type": "integer",
                        "direction": "input",
                        "data_updated_at": "2026-04-04T10:00:00Z",
                    }
                },
                {
                    "property": {
                        "name": "STATUS",
                        "value": "idle",
                        "base_type": "string",
                        "direction": "output",
                        "data_updated_at": "2026-04-04T10:01:00Z",
                    }
                },
            ],
        )
    )

    props = await ayla_client.get_device_properties("DSN001")
    assert len(props) == 2
    assert props[0].name == "POWER"
    assert props[0].value == 1
    assert props[0].read_only is False
    assert props[1].name == "STATUS"
    assert props[1].read_only is True


@pytest.mark.asyncio
@respx.mock
async def test_get_property(ayla_client: AylaClient) -> None:
    respx.post("https://auth.test.example.com/api/v1/token_sign_in").mock(
        return_value=Response(200, json={"access_token": "tok", "refresh_token": "ref"})
    )
    await ayla_client.authenticate()

    respx.get(
        "https://ads.test.example.com/apiv1/dsns/DSN001/properties/POWER.json"
    ).mock(
        return_value=Response(
            200,
            json={
                "property": {
                    "name": "POWER",
                    "value": 1,
                    "base_type": "integer",
                    "direction": "input",
                }
            },
        )
    )

    prop = await ayla_client.get_property("POWER", "DSN001")
    assert prop.name == "POWER"
    assert prop.value == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_property_not_found(ayla_client: AylaClient) -> None:
    respx.post("https://auth.test.example.com/api/v1/token_sign_in").mock(
        return_value=Response(200, json={"access_token": "tok", "refresh_token": "ref"})
    )
    await ayla_client.authenticate()

    respx.get(
        "https://ads.test.example.com/apiv1/dsns/DSN001/properties/NONEXISTENT.json"
    ).mock(return_value=Response(404, json={"error": "not found"}))

    with pytest.raises(PropertyNotFoundError, match="NONEXISTENT"):
        await ayla_client.get_property("NONEXISTENT", "DSN001")


@pytest.mark.asyncio
@respx.mock
async def test_set_property(ayla_client: AylaClient) -> None:
    respx.post("https://auth.test.example.com/api/v1/token_sign_in").mock(
        return_value=Response(200, json={"access_token": "tok", "refresh_token": "ref"})
    )
    await ayla_client.authenticate()

    route = respx.post(
        "https://ads.test.example.com/apiv1/dsns/DSN001/properties/POWER/datapoints.json"
    ).mock(
        return_value=Response(
            201, json={"datapoint": {"value": 1, "created_at": "2026-04-04T10:05:00Z"}}
        )
    )

    result = await ayla_client.set_property("POWER", 1, "DSN001")
    assert result["datapoint"]["value"] == 1
    assert route.call_count == 1

    # Verify request body
    request = route.calls[0].request
    import json

    body = json.loads(request.content)
    assert body == {"datapoint": {"value": 1}}


@pytest.mark.asyncio
@respx.mock
async def test_resolve_dsn_auto_select(ayla_client: AylaClient) -> None:
    respx.post("https://auth.test.example.com/api/v1/token_sign_in").mock(
        return_value=Response(200, json={"access_token": "tok", "refresh_token": "ref"})
    )
    await ayla_client.authenticate()

    respx.get("https://ads.test.example.com/apiv1/devices.json").mock(
        return_value=Response(
            200,
            json=[
                {
                    "device": {
                        "dsn": "DSN001",
                        "id": 1,
                        "product_name": "X",
                        "model": "Y",
                    }
                }
            ],
        )
    )
    await ayla_client.list_devices()

    # Should auto-resolve to the single device
    respx.get("https://ads.test.example.com/apiv1/dsns/DSN001/properties.json").mock(
        return_value=Response(200, json=[])
    )

    props = await ayla_client.get_device_properties()
    assert props == []


@pytest.mark.asyncio
@respx.mock
async def test_resolve_dsn_multiple_devices_requires_dsn(
    ayla_client: AylaClient,
) -> None:
    respx.post("https://auth.test.example.com/api/v1/token_sign_in").mock(
        return_value=Response(200, json={"access_token": "tok", "refresh_token": "ref"})
    )
    await ayla_client.authenticate()

    respx.get("https://ads.test.example.com/apiv1/devices.json").mock(
        return_value=Response(
            200,
            json=[
                {
                    "device": {
                        "dsn": "DSN001",
                        "id": 1,
                        "product_name": "X",
                        "model": "Y",
                    }
                },
                {
                    "device": {
                        "dsn": "DSN002",
                        "id": 2,
                        "product_name": "Z",
                        "model": "W",
                    }
                },
            ],
        )
    )
    await ayla_client.list_devices()

    with pytest.raises(DeviceNotFoundError, match="Multiple devices"):
        await ayla_client.get_device_properties()


@pytest.mark.asyncio
@respx.mock
async def test_token_refresh_on_401(ayla_client: AylaClient) -> None:
    """Test that a 401 response triggers token refresh and retry."""
    respx.post("https://auth.test.example.com/api/v1/token_sign_in").mock(
        return_value=Response(
            200, json={"access_token": "tok_old", "refresh_token": "ref"}
        )
    )
    await ayla_client.authenticate()

    refresh_route = respx.post(
        "https://auth.test.example.com/users/refresh_token.json"
    ).mock(
        return_value=Response(
            200, json={"access_token": "tok_new", "refresh_token": "ref_new"}
        )
    )

    # First call returns 401, second (after refresh) returns 200
    devices_route = respx.get("https://ads.test.example.com/apiv1/devices.json").mock(
        side_effect=[
            Response(401, json={"error": "unauthorized"}),
            Response(200, json=[]),
        ]
    )

    devices = await ayla_client.list_devices()
    assert devices == []
    assert refresh_route.call_count == 1
    assert devices_route.call_count == 2


# --- Gigya email/password auth tests ---


@pytest.fixture
def gigya_settings() -> AylaSettings:
    return AylaSettings(
        ayla_app_id="test-app-id",
        ayla_app_secret="test-app-secret",
        ayla_sso_token=SecretStr(""),
        email="test@example.com",
        password=SecretStr("test-password"),
        ayla_auth_base_url="https://auth.test.example.com",
        ayla_ads_base_url="https://ads.test.example.com",
    )


@pytest.fixture
def gigya_client(
    http_client: httpx.AsyncClient, gigya_settings: AylaSettings, tmp_path: pathlib.Path
) -> AylaClient:
    return AylaClient(
        http_client, gigya_settings, token_file=tmp_path / ".ayla_token.json"
    )


GIGYA_LOGIN_URL = "https://accounts.eu1.gigya.com/accounts.login"


def _mock_gigya_login_success() -> respx.Route:
    return respx.post(GIGYA_LOGIN_URL).mock(
        return_value=Response(
            200,
            json={
                "errorCode": 0,
                "statusCode": 200,
                "id_token": "gigya-jwt-token",
                "sessionInfo": {
                    "sessionToken": "st2.s.tok",
                    "sessionSecret": "test-session-secret",
                    "expires_in": "7776000",
                },
            },
        )
    )


def _mock_ayla_sso_success() -> respx.Route:
    return respx.post("https://auth.test.example.com/api/v1/token_sign_in").mock(
        return_value=Response(
            200,
            json={
                "access_token": "tok_gigya",
                "refresh_token": "ref_gigya",
                "role": "EndUser",
            },
        )
    )


@pytest.mark.asyncio
@respx.mock
async def test_authenticate_gigya_success(gigya_client: AylaClient) -> None:
    _mock_gigya_login_success()
    _mock_ayla_sso_success()

    auth = await gigya_client.authenticate()
    assert auth.access_token == "tok_gigya"
    assert auth.refresh_token == "ref_gigya"
    assert auth.role == "EndUser"
    assert gigya_client.is_authenticated


@pytest.mark.asyncio
@respx.mock
async def test_authenticate_gigya_bad_credentials(gigya_client: AylaClient) -> None:
    respx.post(GIGYA_LOGIN_URL).mock(
        return_value=Response(
            403,
            json={
                "errorCode": 403042,
                "errorMessage": "Invalid LoginID",
                "errorDetails": "loginID does not match any existing account",
                "statusCode": 403,
            },
        )
    )

    with pytest.raises(AuthenticationError, match="Gigya login failed with status 403"):
        await gigya_client.authenticate()


@pytest.mark.asyncio
@respx.mock
async def test_authenticate_gigya_error_in_body(gigya_client: AylaClient) -> None:
    """Gigya can return 200 with a non-zero errorCode in the body."""
    respx.post(GIGYA_LOGIN_URL).mock(
        return_value=Response(
            200,
            json={
                "errorCode": 403042,
                "errorMessage": "Invalid LoginID",
                "errorDetails": "loginID does not match any existing account",
                "statusCode": 403,
            },
        )
    )

    with pytest.raises(AuthenticationError, match="loginID does not match"):
        await gigya_client.authenticate()


@pytest.mark.asyncio
@respx.mock
async def test_authenticate_gigya_missing_id_token(
    gigya_client: AylaClient,
) -> None:
    respx.post(GIGYA_LOGIN_URL).mock(
        return_value=Response(
            200,
            json={"errorCode": 0, "statusCode": 200},
        )
    )

    with pytest.raises(AuthenticationError, match="missing id_token"):
        await gigya_client.authenticate()


@pytest.mark.asyncio
@respx.mock
async def test_authenticate_prefers_gigya_over_sso(tmp_path: pathlib.Path) -> None:
    """When both email/password and SSO token are set, Gigya is tried first."""
    settings = AylaSettings(
        ayla_app_id="test-app-id",
        ayla_app_secret="test-app-secret",
        ayla_sso_token=SecretStr("should-not-be-used"),
        email="test@example.com",
        password=SecretStr("test-password"),
        ayla_auth_base_url="https://auth.test.example.com",
        ayla_ads_base_url="https://ads.test.example.com",
    )
    client = AylaClient(
        httpx.AsyncClient(), settings, token_file=tmp_path / ".ayla_token.json"
    )

    login_route = _mock_gigya_login_success()
    _mock_ayla_sso_success()

    auth = await client.authenticate()
    assert auth.access_token == "tok_gigya"
    # Gigya login was called (not direct SSO)
    assert login_route.call_count == 1
