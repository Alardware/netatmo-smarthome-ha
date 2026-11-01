"""Binary sensor platform: smoke and carbon monoxide alarms."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NetatmoConfigEntry
from .const import CO_TYPES, SMOKE_TYPES
from .coordinator import NetatmoAlarm, NetatmoCoordinator
from .entity import NetatmoModuleEntity, async_add_new_modules

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NetatmoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up alarm binary sensors."""
    coordinator = entry.runtime_data
    async_add_new_modules(
        coordinator,
        entry.async_on_unload,
        lambda module: module.type in SMOKE_TYPES | CO_TYPES,
        lambda ids: async_add_entities(NetatmoAlarmSensor(coordinator, i) for i in ids),
    )


class NetatmoAlarmSensor(NetatmoModuleEntity, BinarySensorEntity):
    """Smoke or CO detected, rebuilt from Netatmo events.

    Netatmo publishes no alarm state, only events: the sensor turns on with a
    detection event, off with a "cleared" event, and off by itself 30 minutes
    after a detection that was never cleared.
    """

    _attr_name = None

    def __init__(self, coordinator: NetatmoCoordinator, module_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, module_id)
        self._attr_unique_id = f"{module_id}_alarm"
        self._smoke = self.module.type in SMOKE_TYPES
        self._attr_device_class = (
            BinarySensorDeviceClass.SMOKE if self._smoke else BinarySensorDeviceClass.CO
        )

    @property
    def _alarm(self) -> NetatmoAlarm:
        return self.coordinator.data.alarms.get(self._module_id) or NetatmoAlarm()

    @property
    def available(self) -> bool:
        """Alarms stay available: Netatmo reports detectors only through events."""
        return (
            self.coordinator.last_update_success
            and self._module_id in self.coordinator.data.modules
        )

    @property
    def is_on(self) -> bool:
        """Return True while smoke or CO is detected."""
        alarm = self._alarm
        return alarm.smoke if self._smoke else alarm.co_level > 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the last event received from the detector."""
        alarm = self._alarm
        return {
            "last_event": alarm.last_event,
            "last_event_time": alarm.last_event_time.isoformat()
            if alarm.last_event_time
            else None,
        }
