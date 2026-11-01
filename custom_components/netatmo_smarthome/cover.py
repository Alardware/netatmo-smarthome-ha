"""Cover platform: Bubendorff (iDiamant) and Legrand shutters, garage doors."""

from __future__ import annotations

from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NetatmoConfigEntry
from .const import COVER_TYPES, GARAGE_TYPES
from .coordinator import NetatmoCoordinator, NetatmoModule
from .entity import NetatmoModuleEntity, async_add_new_modules

PARALLEL_UPDATES = 1

OPEN, CLOSED, STOP = 100, 0, -1


def is_cover(module: NetatmoModule) -> bool:
    """Return True for shutters and garage doors."""
    return module.type in COVER_TYPES | GARAGE_TYPES


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NetatmoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up covers."""
    coordinator = entry.runtime_data
    async_add_new_modules(
        coordinator,
        entry.async_on_unload,
        is_cover,
        lambda ids: async_add_entities(NetatmoCover(coordinator, i) for i in ids),
    )


class NetatmoCover(NetatmoModuleEntity, CoverEntity):
    """A shutter driven through a Netatmo gateway.

    Shutters whose position step is 100 only open, close and stop: their
    current_position just repeats the last command, so no position is shown.
    """

    _attr_name = None

    def __init__(self, coordinator: NetatmoCoordinator, module_id: str) -> None:
        """Initialize the cover."""
        super().__init__(coordinator, module_id)
        self._attr_unique_id = module_id
        # Position commanded from Home Assistant and not reached yet: Netatmo
        # often reports the old position until the shutter stops.
        self._commanded: int | None = None
        self._attr_device_class = (
            CoverDeviceClass.GARAGE
            if self.module.type in GARAGE_TYPES
            else CoverDeviceClass.SHUTTER
        )

    @property
    def _step(self) -> int:
        status = self.module.status
        step = _int(
            status.get("target_position:step", status.get("target_position_step"))
        )
        return step if step is not None else 100

    @property
    def _positionable(self) -> bool:
        return self._step < 100

    @property
    def supported_features(self) -> CoverEntityFeature:
        """Open, close and stop; set position when the shutter supports it."""
        features = (
            CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
        )
        if self._positionable:
            features |= CoverEntityFeature.SET_POSITION
        return features

    @property
    def _current(self) -> int | None:
        position = _int(self.module.status.get("current_position"))
        return position if position is not None and 0 <= position <= 100 else None

    @property
    def current_cover_position(self) -> int | None:
        """Return the measured position, for positionable shutters only."""
        return self._current if self._positionable else None

    @property
    def is_closed(self) -> bool | None:
        """Return True when the shutter is closed."""
        current = self._current
        return None if current is None else current == CLOSED

    @property
    def _target(self) -> int | None:
        if self._commanded is not None:
            return self._commanded
        target = _int(self.module.status.get("target_position"))
        return target if target is not None and 0 <= target <= 100 else None

    @property
    def is_opening(self) -> bool:
        """Return True while the shutter moves up."""
        target, current = self._target, self._current
        return target is not None and current is not None and target > current

    @property
    def is_closing(self) -> bool:
        """Return True while the shutter moves down."""
        target, current = self._target, self._current
        return target is not None and current is not None and target < current

    def _still_moving(self) -> bool:
        return self._commanded is not None

    @callback
    def _follow_up_given_up(self) -> None:
        self._commanded = None
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Forget the commanded position once the shutter reports it."""
        if self._commanded is not None and self._current == self._commanded:
            self._commanded = None
        super()._handle_coordinator_update()

    async def _move(self, target: int) -> None:
        self._commanded = target if 0 <= target <= 100 else None
        try:
            await self.async_send(target_position=target)
        except Exception:
            self._commanded = None
            raise

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the shutter."""
        await self._move(OPEN)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the shutter."""
        await self._move(CLOSED)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the shutter."""
        await self._move(STOP)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move to a position, rounded to the shutter's step."""
        step = max(self._step, 1)
        position = min(100, max(0, round(kwargs[ATTR_POSITION] / step) * step))
        await self._move(position)
