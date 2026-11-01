"""Light platform: Legrand light switches, micromodules and dimmers."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NetatmoConfigEntry
from .const import DIMMER_TYPES, LIGHT_TYPES
from .coordinator import NetatmoCoordinator, NetatmoModule
from .entity import NetatmoModuleEntity, async_add_new_modules

PARALLEL_UPDATES = 1


def is_light(module: NetatmoModule) -> bool:
    """Return True for light modules; a double switch is exposed per gang."""
    if module.type in DIMMER_TYPES:
        return True
    if module.type in LIGHT_TYPES:
        return "#" in module.id or module.type != "NLIS"
    return False


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NetatmoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up lights."""
    coordinator = entry.runtime_data
    async_add_new_modules(
        coordinator,
        entry.async_on_unload,
        is_light,
        lambda ids: async_add_entities(NetatmoLight(coordinator, i) for i in ids),
    )


class NetatmoLight(NetatmoModuleEntity, LightEntity):
    """A Legrand light."""

    _attr_name = None

    def __init__(self, coordinator: NetatmoCoordinator, module_id: str) -> None:
        """Initialize the light."""
        super().__init__(coordinator, module_id)
        self._attr_unique_id = module_id
        mode = (
            ColorMode.BRIGHTNESS
            if self.module.type in DIMMER_TYPES
            else ColorMode.ONOFF
        )
        self._attr_color_mode = mode
        self._attr_supported_color_modes = {mode}

    @property
    def is_on(self) -> bool | None:
        """Return True if the light is on."""
        value = self.module.status.get("on")
        return None if value is None else bool(value)

    @property
    def brightness(self) -> int | None:
        """Return the brightness (0-255)."""
        level = self.module.status.get("brightness")
        if self._attr_color_mode != ColorMode.BRIGHTNESS or level is None:
            return None
        return round(int(level) * 255 / 100)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on, optionally at a brightness."""
        if ATTR_BRIGHTNESS in kwargs and self._attr_color_mode == ColorMode.BRIGHTNESS:
            level = max(1, round(kwargs[ATTR_BRIGHTNESS] * 100 / 255))
            await self.async_send(on=True, brightness=level)
        else:
            await self.async_send(on=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        await self.async_send(on=False)
