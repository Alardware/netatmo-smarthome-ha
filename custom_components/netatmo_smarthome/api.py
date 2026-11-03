"""Minimal client for the Netatmo Connect API.

Uses Home Assistant's OAuth2Session, which serialises token refreshes and
saves every new (rotating) refresh token in the config entry right away.
"""

from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import ClientError, ClientResponseError, ClientTimeout
from homeassistant.helpers.config_entry_oauth2_flow import OAuth2Session

from .const import API_URL

REQUEST_TIMEOUT = ClientTimeout(total=20)
# Netatmo often answers 503 to third-party apps under load: retry reads once.
RETRY_DELAY = 3

# Error codes found in the JSON body of a failed request.
THROTTLE_CODES = {26, 28, 29}
TOKEN_CODES = {2, 3}
SCOPE_CODE = 13
# setstate per-module code meaning "already in that state".
NOTHING_TO_MODIFY = 23


class NetatmoError(Exception):
    """Base error raised by the Netatmo client."""


class NetatmoConnectionError(NetatmoError):
    """The API could not be reached."""


class NetatmoAuthError(NetatmoError):
    """The access token was refused or could not be refreshed."""

    def __init__(self, message: str, status: int | None = None) -> None:
        """Store the HTTP status of the failure."""
        self.status = status
        super().__init__(message)


class NetatmoScopeError(NetatmoError):
    """The token lacks a permission (scope) needed for the request."""


class NetatmoThrottledError(NetatmoError):
    """Netatmo asked to slow down."""

    def __init__(self, retry_after: float | None) -> None:
        """Store how long to wait, if Netatmo said."""
        self.retry_after = retry_after
        super().__init__("Netatmo request limit reached")


class NetatmoApiError(NetatmoError):
    """Any other API error."""


class NetatmoServerError(NetatmoApiError):
    """Netatmo is overloaded or down (HTTP 5xx); usually gone seconds later."""


class NetatmoCommandError(NetatmoError):
    """setstate answered with per-module errors."""

    def __init__(self, errors: list[dict[str, Any]]) -> None:
        """Store the module errors."""
        self.errors = errors
        super().__init__(f"Netatmo refused the command: {errors}")


def _retry_after(value: str | None) -> float | None:
    try:
        return float(value) if value else None
    except ValueError:
        return None


class NetatmoClient:
    """Read and write the Netatmo homes of one account."""

    def __init__(self, session: OAuth2Session) -> None:
        """Initialize the client."""
        self._session = session

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run a request; retry a read once when Netatmo is busy or unreachable."""
        try:
            return await self._request_once(method, endpoint, params, json)
        except (NetatmoConnectionError, NetatmoServerError):
            if method != "GET":
                raise  # never repeat a command that may already have run
        await asyncio.sleep(RETRY_DELAY)
        return await self._request_once(method, endpoint, params, json)

    async def _request_once(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None,
        json: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Run a request and return the decoded body."""
        try:
            await self._session.async_ensure_token_valid()
        except ClientResponseError as err:
            raise NetatmoAuthError(
                f"Token refresh failed: {err.status}", err.status
            ) from err
        except (ClientError, TimeoutError) as err:
            raise NetatmoConnectionError(str(err) or type(err).__name__) from err

        try:
            resp = await self._session.async_request(
                method,
                f"{API_URL}/{endpoint}",
                params=params,
                json=json,
                timeout=REQUEST_TIMEOUT,
            )
            async with resp:
                try:
                    data = await resp.json(content_type=None)
                except ValueError:
                    data = None
                if resp.status >= 400 or not isinstance(data, dict):
                    self._raise_for(resp.status, data, resp.headers.get("Retry-After"))
                return data
        except (ClientError, TimeoutError) as err:
            raise NetatmoConnectionError(str(err) or type(err).__name__) from err

    @staticmethod
    def _raise_for(status: int, data: Any, retry_after: str | None) -> None:
        error = data.get("error", {}) if isinstance(data, dict) else {}
        code = error.get("code") if isinstance(error, dict) else None
        message = error.get("message", "") if isinstance(error, dict) else ""
        if status == 429 or code in THROTTLE_CODES:
            raise NetatmoThrottledError(_retry_after(retry_after))
        if code == SCOPE_CODE:
            raise NetatmoScopeError(message or "Missing permission")
        if status == 401 or code in TOKEN_CODES:
            raise NetatmoAuthError(message or "Invalid access token", status)
        error = f"HTTP {status} code {code}: {message}".strip()
        if status >= 500:
            raise NetatmoServerError(error)
        raise NetatmoApiError(error)

    async def async_get_homes(self) -> list[dict[str, Any]]:
        """Return the homes, rooms and modules of the account."""
        data = await self._request("GET", "homesdata")
        homes = data.get("body", {}).get("homes")
        return homes if isinstance(homes, list) else []

    async def async_get_home_status(self, home_id: str) -> dict[str, Any]:
        """Return the live state of a home ({"modules": [...], "errors": [...]})."""
        data = await self._request("GET", "homestatus", params={"home_id": home_id})
        body = data.get("body", {})
        home = body.get("home", {}) if isinstance(body, dict) else {}
        errors = home.get("errors") or body.get("errors") or []
        return {"modules": home.get("modules") or [], "errors": errors}

    async def async_get_events(
        self, home_id: str, size: int = 30
    ) -> list[dict[str, Any]]:
        """Return the latest events of a home, newest first."""
        data = await self._request(
            "GET", "getevents", params={"home_id": home_id, "size": size}
        )
        home = data.get("body", {}).get("home", {})
        events = home.get("events") if isinstance(home, dict) else None
        return events if isinstance(events, list) else []

    async def async_get_homecoaches(self) -> list[dict[str, Any]]:
        """Return the Home Coach devices with their latest measures."""
        data = await self._request("GET", "gethomecoachsdata")
        devices = data.get("body", {}).get("devices")
        return devices if isinstance(devices, list) else []

    async def async_set_state(
        self, home_id: str, modules: list[dict[str, Any]]
    ) -> None:
        """Send commands; raise NetatmoCommandError on per-module failures."""
        data = await self._request(
            "POST", "setstate", json={"home": {"id": home_id, "modules": modules}}
        )
        errors = [
            error
            for error in (data.get("body") or {}).get("errors") or []
            if error.get("code") != NOTHING_TO_MODIFY
        ]
        if errors:
            raise NetatmoCommandError(errors)
