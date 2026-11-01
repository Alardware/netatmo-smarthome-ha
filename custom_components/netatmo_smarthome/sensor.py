"""Sensor platform: Home Coach measures, power, alarm batteries and CO level."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    CONCENTRATION_PARTS_PER_MILLION,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfPower,
    UnitOfPressure,
    UnitOfSoundPressure,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import NetatmoConfigEntry
from .const import ATTRIBUTION, CO_LEVELS, CO_TYPES, DOMAIN, HEALTH_LEVELS, SMOKE_TYPES
from .coordinator import NetatmoCoordinator
from .entity import NetatmoModuleEntity, async_add_new_modules

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class HomeCoachSensorDescription(SensorEntityDescription):
    """Describe a Home Coach measure."""

    field: str
    value_fn: Callable[[Any], Any] = lambda value: value


HOMECOACH_SENSORS: tuple[HomeCoachSensorDescription, ...] = (
    HomeCoachSensorDescription(
        key="temperature",
        field="Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HomeCoachSensorDescription(
        key="humidity",
        field="Humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HomeCoachSensorDescription(
        key="co2",
        field="CO2",
        device_class=SensorDeviceClass.CO2,
        native_unit_of_measurement=CONCENTRATION_PARTS_PER_MILLION,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HomeCoachSensorDescription(
        key="noise",
        field="Noise",
        device_class=SensorDeviceClass.SOUND_PRESSURE,
        native_unit_of_measurement=UnitOfSoundPressure.DECIBEL,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HomeCoachSensorDescription(
        key="pressure",
        field="Pressure",
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        native_unit_of_measurement=UnitOfPressure.MBAR,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HomeCoachSensorDescription(
        key="health",
        translation_key="health",
        field="health_idx",
        device_class=SensorDeviceClass.ENUM,
        options=HEALTH_LEVELS,
        value_fn=lambda value: (
            HEALTH_LEVELS[value]
            if isinstance(value, int) and 0 <= value < len(HEALTH_LEVELS)
            else None
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NetatmoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = entry.runtime_data

    async_add_new_modules(
        coordinator,
        entry.async_on_unload,
        lambda module: "power" in module.status,
        lambda ids: async_add_entities(NetatmoPowerSensor(coordinator, i) for i in ids),
    )
    async_add_new_modules(
        coordinator,
        entry.async_on_unload,
        lambda module: (
            "battery_percent" in module.status or "battery_state" in module.status
        ),
        lambda ids: async_add_entities(
            NetatmoBatterySensor(coordinator, i) for i in ids
        ),
    )
    async_add_new_modules(
        coordinator,
        entry.async_on_unload,
        lambda module: module.type in SMOKE_TYPES | CO_TYPES,
        lambda ids: async_add_entities(
            NetatmoLastSeenSensor(coordinator, i) for i in ids
        ),
    )
    async_add_new_modules(
        coordinator,
        entry.async_on_unload,
        lambda module: "wifi_strength" in module.status,
        lambda ids: async_add_entities(NetatmoWifiSensor(coordinator, i) for i in ids),
    )
    async_add_new_modules(
        coordinator,
        entry.async_on_unload,
        lambda module: module.type in CO_TYPES,
        lambda ids: async_add_entities(
            NetatmoCoLevelSensor(coordinator, i) for i in ids
        ),
    )

    known: set[str] = set()

    @callback
    def _add_homecoaches() -> None:
        new = [i for i in coordinator.data.homecoaches if i not in known]
        if new:
            known.update(new)
            async_add_entities(
                HomeCoachSensor(coordinator, coach_id, description)
                for coach_id in new
                for description in HOMECOACH_SENSORS
            )

    _add_homecoaches()
    entry.async_on_unload(coordinator.async_add_listener(_add_homecoaches))


class NetatmoPowerSensor(NetatmoModuleEntity, SensorEntity):
    """Power drawn through a Legrand module."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: NetatmoCoordinator, module_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, module_id)
        self._attr_unique_id = f"{module_id}_power"

    @property
    def native_value(self) -> float | None:
        """Return the power in W."""
        power = self.module.status.get("power")
        return power if isinstance(power, int | float) and power >= 0 else None


class NetatmoDiagnosticSensor(NetatmoModuleEntity, SensorEntity):
    """Diagnostic value that stays readable for sleeping battery modules."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        """Remotes and alarms sleep and report reachable: false; keep them."""
        return (
            self.coordinator.last_update_success
            and self._module_id in self.coordinator.data.modules
        )


class NetatmoLastSeenSensor(NetatmoDiagnosticSensor):
    """Last time a smoke or CO alarm contacted Netatmo (about once a month)."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "last_seen"

    def __init__(self, coordinator: NetatmoCoordinator, module_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, module_id)
        self._attr_unique_id = f"{module_id}_last_seen"

    @property
    def native_value(self) -> datetime | None:
        """Return the last contact time."""
        seen = self.module.status.get("last_seen")
        if isinstance(seen, int | float) and seen > 0:
            return dt_util.utc_from_timestamp(seen)
        return None


class NetatmoWifiSensor(NetatmoDiagnosticSensor):
    """Wi-Fi signal of a gateway or an alarm.

    Netatmo reports the signal as a positive number where lower is better (it
    is the RSSI without its sign), so it is shown in dBm as a negative value.
    """

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: NetatmoCoordinator, module_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, module_id)
        self._attr_unique_id = f"{module_id}_wifi"

    @property
    def native_value(self) -> int | None:
        """Return the Wi-Fi signal in dBm."""
        strength = self.module.status.get("wifi_strength")
        return -int(strength) if isinstance(strength, int | float) else None


class NetatmoBatterySensor(NetatmoDiagnosticSensor):
    """Battery level of a module that reports one (remotes, switches)."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: NetatmoCoordinator, module_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, module_id)
        self._attr_unique_id = f"{module_id}_battery"

    @property
    def native_value(self) -> int | None:
        """Return the battery level when Netatmo reports it."""
        status = self.module.status
        level = status.get("battery_percent")
        if isinstance(level, int | float):
            return int(level)
        return {
            "max": 100,
            "full": 90,
            "high": 75,
            "medium": 50,
            "low": 25,
            "very_low": 10,
        }.get(str(status.get("battery_state")))


class NetatmoCoLevelSensor(NetatmoModuleEntity, SensorEntity):
    """Carbon monoxide alarm level (ok, pre-alarm, alarm)."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(CO_LEVELS.values())
    _attr_translation_key = "co_level"

    def __init__(self, coordinator: NetatmoCoordinator, module_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, module_id)
        self._attr_unique_id = f"{module_id}_co_level"

    @property
    def native_value(self) -> str | None:
        """Return the CO alarm level."""
        alarm = self.coordinator.data.alarms.get(self._module_id)
        return CO_LEVELS.get(alarm.co_level) if alarm else None


class HomeCoachSensor(CoordinatorEntity[NetatmoCoordinator], SensorEntity):
    """A measure of a Healthy Home Coach."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True
    entity_description: HomeCoachSensorDescription

    def __init__(
        self,
        coordinator: NetatmoCoordinator,
        coach_id: str,
        description: HomeCoachSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._coach_id = coach_id
        self._attr_unique_id = f"{coach_id}_{description.key}"
        coach = coordinator.data.homecoaches[coach_id]
        name = coach.get("station_name") or coach.get("module_name") or "Home Coach"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coach_id)},
            manufacturer="Netatmo",
            model="Healthy Home Coach",
            name=name,
            sw_version=str(coach.get("firmware") or "") or None,
        )

    @property
    def _coach(self) -> dict[str, Any]:
        return self.coordinator.data.homecoaches.get(self._coach_id, {})

    @property
    def available(self) -> bool:
        """Return True when the Home Coach sends measures."""
        coach = self._coach
        return (
            super().available
            and coach.get("reachable") is not False
            and isinstance(coach.get("dashboard_data"), dict)
        )

    @property
    def native_value(self) -> Any:
        """Return the measure."""
        value = (self._coach.get("dashboard_data") or {}).get(
            self.entity_description.field
        )
        return None if value is None else self.entity_description.value_fn(value)
