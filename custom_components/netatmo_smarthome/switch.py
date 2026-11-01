"""Switch platform: Legrand outlets, relays and contactors."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NetatmoConfigEntry
from .const import OUTLET_TYPES, SWITCH_TYPES
from .coordinator import NetatmoCoordinator, NetatmoModule
from .entity import NetatmoModuleEntity, async_add_new_modules

PARALLEL_UPDATES = 1


def is_switch(module: NetatmoModule) -> bool:
    """Return True for on/off modules that are not lights."""
    return module.type in SWITCH_TYPES


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NetatmoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up switches."""
    coordinator = entry.runtime_data
    async_add_new_modules(
        coordinator,
        entry.async_on_unload,
        is_switch,
        lambda ids: async_add_entities(NetatmoSwitch(coordinator, i) for i in ids),
    )


class NetatmoSwitch(NetatmoModuleEntity, SwitchEntity):
    """A Legrand outlet or relay."""

    _attr_name = None

    def __init__(self, coordinator: NetatmoCoordinator, module_id: str) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, module_id)
        self._attr_unique_id = module_id
        if self.module.type in OUTLET_TYPES:
            self._attr_device_class = SwitchDeviceClass.OUTLET

    @property
    def is_on(self) -> bool | None:
        """Return True if the switch is on."""
        value = self.module.status.get("on")
        return None if value is None else bool(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self.async_send(on=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self.async_send(on=False)
