"""Data update coordinator for the Netatmo Smart Home integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    NetatmoAuthError,
    NetatmoClient,
    NetatmoError,
    NetatmoScopeError,
    NetatmoThrottledError,
)
from .const import (
    ALARM_TIMEOUT,
    CO_TYPES,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENTS_EVERY,
    HOMECOACH_EVERY,
    LOGGER,
    MAX_BACKOFF,
    MAX_TOKEN_FAILURES,
    SMOKE_TYPES,
    STALE_TOLERANCE,
    THROTTLE_DELAY,
    TOPOLOGY_INTERVAL,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

ALARM_TYPES = SMOKE_TYPES | CO_TYPES


@dataclass(slots=True)
class NetatmoModule:
    """A module of a Netatmo home (gateway, outlet, shutter, alarm...)."""

    id: str
    home_id: str
    type: str
    name: str
    bridge: str | None = None
    room: str | None = None
    status: dict[str, Any] = field(default_factory=dict)
    reachable: bool = True

    @property
    def parent_id(self) -> str:
        """Return the module carrying this gang (`<id>#<n>`), or the module."""
        return self.id.split("#", 1)[0]


@dataclass(slots=True)
class NetatmoAlarm:
    """Alarm state of a smoke or CO detector, rebuilt from events."""

    smoke: bool = False
    co_level: int = 0
    last_event: str | None = None
    last_event_time: datetime | None = None
    detected_at: datetime | None = None


@dataclass(slots=True)
class NetatmoData:
    """Everything the entities read."""

    modules: dict[str, NetatmoModule] = field(default_factory=dict)
    homecoaches: dict[str, dict[str, Any]] = field(default_factory=dict)
    alarms: dict[str, NetatmoAlarm] = field(default_factory=dict)


def _event_time(event: dict[str, Any]) -> datetime | None:
    try:
        return dt_util.utc_from_timestamp(int(event["time"]))
    except (KeyError, TypeError, ValueError):
        return None


def apply_events(
    alarms: dict[str, NetatmoAlarm],
    events: list[dict[str, Any]],
    seen: set[str],
    now: datetime,
) -> None:
    """Update alarm states with smoke/CO events not seen yet (oldest first).

    Events older than ALARM_TIMEOUT only refresh the "last event" fields, so
    an alarm still running when Home Assistant starts is shown, and an old one
    is not replayed.
    """
    for event in sorted(events, key=lambda e: e.get("time") or 0):
        event_id = str(event.get("id") or f"{event.get('time')}-{event.get('type')}")
        module_id = event.get("module_id") or event.get("device_id")
        if event_id in seen or module_id not in alarms:
            continue
        seen.add(event_id)
        alarm = alarms[module_id]
        when = _event_time(event)
        kind = str(event.get("type") or "")
        try:
            sub_type = int(event.get("sub_type", -1))
        except (TypeError, ValueError):
            sub_type = -1
        alarm.last_event = kind
        alarm.last_event_time = when
        recent = when is not None and now - when < ALARM_TIMEOUT
        if kind == "smoke" and sub_type in (0, 1):
            alarm.smoke = sub_type == 1 and recent
        elif kind == "co_detected" and sub_type in (0, 1, 2):
            alarm.co_level = sub_type if recent else 0
        else:
            continue
        if alarm.smoke or alarm.co_level:
            alarm.detected_at = when
    # A detection without its "cleared" event does not stay on forever.
    for alarm in alarms.values():
        if alarm.detected_at and now - alarm.detected_at >= ALARM_TIMEOUT:
            alarm.smoke, alarm.co_level, alarm.detected_at = False, 0, None


class NetatmoCoordinator(DataUpdateCoordinator[NetatmoData]):
    """Poll the Netatmo homes of one account."""

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: NetatmoClient
    ) -> None:
        """Initialize the coordinator."""
        seconds = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=seconds),
        )
        self.client = client
        self.homes: list[dict[str, Any]] = []
        self.home_names: dict[str, str] = {}
        self._topology_at: datetime | None = None
        self._cycle = 0
        self._seen_events: set[str] = set()
        self._token_failures = 0
        self._failures = 0
        self._homecoach_allowed = True
        self._base_interval = timedelta(seconds=seconds)
        # Options the entry was loaded with: a new token must not reload it.
        self.loaded_options = dict(entry.options)
        self.raw: dict[str, Any] = {}

    async def _async_update_data(self) -> NetatmoData:
        """Fetch topology (rarely), statuses, alarm events and Home Coach data."""
        previous = self.data or NetatmoData()
        try:
            data = await self._fetch(previous)
        except NetatmoThrottledError as err:
            raise UpdateFailed(
                "Netatmo request limit reached, pausing",
                retry_after=err.retry_after or THROTTLE_DELAY,
            ) from err
        except NetatmoScopeError as err:
            raise ConfigEntryAuthFailed(f"Missing Netatmo permission: {err}") from err
        except NetatmoAuthError as err:
            self._token_failures += 1
            if self._token_failures >= MAX_TOKEN_FAILURES:
                raise ConfigEntryAuthFailed(str(err)) from err
            return self._keep_last_values(err)
        except NetatmoError as err:
            return self._keep_last_values(err)
        self._token_failures = 0
        self._failures = 0
        self.update_interval = self._base_interval
        self._cycle += 1
        return data

    def _keep_last_values(self, err: NetatmoError) -> NetatmoData:
        """Keep the last values through a few failed updates in a row."""
        self._failures += 1
        # Slow down while Netatmo refuses, so a busy server is not hammered.
        self.update_interval = timedelta(
            seconds=min(
                self._base_interval.total_seconds() * 2**self._failures, MAX_BACKOFF
            )
        )
        if self.data is not None and self._failures < STALE_TOLERANCE:
            LOGGER.debug(
                "Netatmo update failed (%s in a row), keeping the last values: %s",
                self._failures,
                err,
            )
            return self.data
        raise UpdateFailed(f"Error communicating with Netatmo: {err}") from err

    async def _fetch(self, previous: NetatmoData) -> NetatmoData:
        now = dt_util.utcnow()
        if self._topology_at is None or now - self._topology_at >= TOPOLOGY_INTERVAL:
            self.homes = await self.client.async_get_homes()
            self.home_names = {h["id"]: h.get("name", h["id"]) for h in self.homes}
            self._topology_at = now
            self.raw["homesdata"] = self.homes

        data = NetatmoData()
        for home in self.homes:
            home_id = home["id"]
            rooms = {r.get("id"): r.get("name") for r in home.get("rooms") or []}
            modules = {
                m["id"]: NetatmoModule(
                    id=m["id"],
                    home_id=home_id,
                    type=str(m.get("type", "")),
                    name=str(m.get("name") or m["id"]),
                    bridge=m.get("bridge"),
                    room=rooms.get(m.get("room_id")),
                )
                for m in home.get("modules") or []
                if "id" in m and m.get("type") not in {"NHC"}
            }
            if not modules:
                continue

            status = await self.client.async_get_home_status(home_id)
            self.raw.setdefault("homestatus", {})[home_id] = status
            offline = {e.get("id") for e in status["errors"] if e.get("code") == 6}
            for state in status["modules"]:
                module = modules.get(state.get("id"))
                if module is not None:
                    module.status = state
                    module.reachable = state.get("reachable", True) is not False
            for module in modules.values():
                if module.id in offline:
                    module.reachable = False
            for module in modules.values():
                parent = modules.get(module.parent_id)
                gateway = modules.get(module.bridge or "")
                if (parent is not None and not parent.reachable) or (
                    gateway is not None and not gateway.reachable
                ):
                    module.reachable = False
            data.modules.update(modules)

            alarm_ids = [m.id for m in modules.values() if m.type in ALARM_TYPES]
            if alarm_ids:
                for module_id in alarm_ids:
                    data.alarms[module_id] = previous.alarms.get(
                        module_id, NetatmoAlarm()
                    )
                events: list[dict[str, Any]] = []
                if self._cycle % EVENTS_EVERY == 0:
                    events = await self.client.async_get_events(home_id)
                    self.raw.setdefault("events", {})[home_id] = events[:10]
                apply_events(data.alarms, events, self._seen_events, now)
                if len(self._seen_events) > 2000:
                    self._seen_events = {str(e.get("id")) for e in events}

        if self._homecoach_allowed and (
            self._cycle % HOMECOACH_EVERY == 0 or not previous.homecoaches
        ):
            try:
                coaches = await self.client.async_get_homecoaches()
            except NetatmoScopeError:
                LOGGER.info("No Home Coach permission, Home Coach data disabled")
                self._homecoach_allowed = False
                coaches = []
            data.homecoaches = {str(c["_id"]): c for c in coaches if "_id" in c}
            self.raw["homecoaches"] = coaches
        else:
            data.homecoaches = previous.homecoaches

        return data
