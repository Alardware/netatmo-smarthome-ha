"""Base entities for the Netatmo Smart Home integration."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import NetatmoCommandError, NetatmoError
from .const import ATTRIBUTION, DOMAIN, MODEL_NAMES, REFRESH_AFTER_COMMAND
from .coordinator import NetatmoCoordinator, NetatmoModule


class NetatmoModuleEntity(CoordinatorEntity[NetatmoCoordinator]):
    """Entity attached to a module of a Netatmo home."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(self, coordinator: NetatmoCoordinator, module_id: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._module_id = module_id
        module = coordinator.data.modules[module_id]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, module.id)},
            manufacturer="Bubendorff"
            if module.type.startswith("NB")
            else "Legrand"
            if module.type.startswith(("NL", "Z3"))
            else "Netatmo",
            model=MODEL_NAMES.get(module.type, module.type),
            name=module.name,
            suggested_area=module.room,
            sw_version=str(module.status.get("firmware_revision") or "") or None,
            via_device=(DOMAIN, module.bridge) if module.bridge else None,
        )

    @property
    def module(self) -> NetatmoModule:
        """Return the latest data of the module."""
        return self.coordinator.data.modules[self._module_id]

    @property
    def available(self) -> bool:
        """Return True if Netatmo can reach the module."""
        modules = self.coordinator.data.modules
        return (
            super().available
            and self._module_id in modules
            and modules[self._module_id].reachable
        )

    async def async_send(self, **values: Any) -> None:
        """Send a command to the module, then read the state back."""
        module = self.module
        command = {"id": module.id, **values}
        if module.bridge:
            command["bridge"] = module.bridge
        try:
            await self.coordinator.client.async_set_state(module.home_id, [command])
        except NetatmoCommandError as err:
            codes = ", ".join(str(e.get("code")) for e in err.errors)
            raise HomeAssistantError(
                f"{module.name}: Netatmo refused the command (code {codes})"
            ) from err
        except NetatmoError as err:
            raise HomeAssistantError(f"{module.name}: {err}") from err
        module.status.update(values)
        self.async_write_ha_state()

        async def _refresh(_now: Any) -> None:
            await self.coordinator.async_request_refresh()

        async_call_later(self.hass, REFRESH_AFTER_COMMAND, _refresh)


def async_add_new_modules(
    coordinator: NetatmoCoordinator,
    async_on_unload: Callable[[Callable[[], None]], None],
    select: Callable[[NetatmoModule], bool],
    add_entities: Callable[[list[str]], None],
) -> None:
    """Add entities for matching modules now and when new ones appear."""
    known: set[str] = set()

    @callback
    def _check() -> None:
        new = [
            module.id
            for module in coordinator.data.modules.values()
            if module.id not in known and select(module)
        ]
        if new:
            known.update(new)
            add_entities(new)

    _check()
    async_on_unload(coordinator.async_add_listener(_check))
