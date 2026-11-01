"""The Netatmo Smart Home integration (unofficial)."""

from __future__ import annotations

from aiohttp import ClientError, ClientResponseError
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_entry_oauth2_flow, device_registry as dr

from .api import NetatmoClient
from .const import (
    DOMAIN,
    GATEWAY_TYPES,
    LOGGER,
    MAX_TOKEN_FAILURES,
    MODEL_NAMES,
    SCOPES,
)
from .coordinator import NetatmoCoordinator

try:
    from homeassistant.helpers.config_entry_oauth2_flow import (
        ImplementationUnavailableError,
    )
except ImportError:  # Home Assistant before 2025.10
    ImplementationUnavailableError = ValueError  # type: ignore[assignment,misc]

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.COVER,
    Platform.LIGHT,
    Platform.SENSOR,
    Platform.SWITCH,
]

type NetatmoConfigEntry = ConfigEntry[NetatmoCoordinator]

# Consecutive refused token refreshes at setup, per entry.
_token_failures: dict[str, int] = {}


async def async_setup_entry(hass: HomeAssistant, entry: NetatmoConfigEntry) -> bool:
    """Set up Netatmo Smart Home from a config entry."""
    try:
        implementation = (
            await config_entry_oauth2_flow.async_get_config_entry_implementation(
                hass, entry
            )
        )
    except ImplementationUnavailableError as err:
        raise ConfigEntryNotReady(
            "Netatmo application credentials are not available"
        ) from err

    session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)
    try:
        await session.async_ensure_token_valid()
    except ClientResponseError as err:
        if err.status in (400, 401):
            # Netatmo also answers 400 during outages: only ask the user to log
            # in again when the refusal repeats.
            failures = _token_failures.get(entry.entry_id, 0) + 1
            _token_failures[entry.entry_id] = failures
            LOGGER.warning(
                "Netatmo refused the token refresh (%s/%s)",
                failures,
                MAX_TOKEN_FAILURES,
            )
            if failures >= MAX_TOKEN_FAILURES:
                raise ConfigEntryAuthFailed("Netatmo token refused") from err
        raise ConfigEntryNotReady(
            f"Netatmo token refresh failed: {err.status}"
        ) from err
    except (ClientError, TimeoutError) as err:
        raise ConfigEntryNotReady(f"Netatmo unreachable: {err}") from err
    _token_failures.pop(entry.entry_id, None)

    granted = session.token.get("scope") or []
    if isinstance(granted, str):
        granted = granted.split()
    if missing := set(SCOPES) - set(granted):
        LOGGER.warning(
            "Netatmo token lacks permissions: %s", ", ".join(sorted(missing))
        )

    coordinator = NetatmoCoordinator(hass, entry, NetatmoClient(session))
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # Gateways have no entity of their own but are the parent of their modules.
    registry = dr.async_get(hass)
    for module in coordinator.data.modules.values():
        if module.type in GATEWAY_TYPES:
            registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, module.id)},
                manufacturer="Bubendorff" if module.type == "NBG" else "Legrand",
                model=MODEL_NAMES.get(module.type, module.type),
                name=module.name,
                sw_version=str(module.status.get("firmware_revision") or "") or None,
            )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NetatmoConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(
    hass: HomeAssistant, entry: NetatmoConfigEntry
) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
