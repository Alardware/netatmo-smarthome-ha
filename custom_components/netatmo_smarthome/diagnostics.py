"""Diagnostics for the Netatmo Smart Home integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import NetatmoConfigEntry

TO_REDACT = {
    "access_token",
    "refresh_token",
    "token",
    "email",
    "user",
    "place",
    "city",
    "coordinates",
    "lat",
    "lon",
    "location",
    "altitude",
    "unique_id",
    "title",
    "snapshot",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NetatmoConfigEntry
) -> dict[str, Any]:
    """Return redacted raw Netatmo answers to help support new modules."""
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "raw": async_redact_data(coordinator.raw, TO_REDACT),
        "alarms": {
            module_id: {
                "smoke": alarm.smoke,
                "co_level": alarm.co_level,
                "last_event": alarm.last_event,
                "last_event_time": alarm.last_event_time.isoformat()
                if alarm.last_event_time
                else None,
            }
            for module_id, alarm in (
                coordinator.data.alarms if coordinator.data else {}
            ).items()
        },
    }
