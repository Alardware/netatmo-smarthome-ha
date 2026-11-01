"""Setup, entities, commands, alarms and diagnostics tests."""

from __future__ import annotations

from datetime import timedelta
import time

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.netatmo_smarthome.const import API_URL, OAUTH2_TOKEN

from .conftest import NBG, NCO, NSD, SHUTTER, events, homestatus, mock_api


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_entities(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    credentials,
    config_entry: MockConfigEntry,
) -> None:
    """Every device of the three apps gets its entities."""
    mock_api(aioclient_mock)
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    assert hass.states.get("switch.prise_sejour").state == "on"
    assert hass.states.get("sensor.prise_sejour_power").state == "120"
    assert hass.states.get("light.applique").state == "off"

    cover = hass.states.get("cover.volet_salon")
    assert cover.state == "closed"
    # Step 100: open/close/stop only, no position.
    assert "current_position" not in cover.attributes

    assert hass.states.get("sensor.capteur_chambre_temperature").state == "20.3"
    assert hass.states.get("sensor.capteur_chambre_carbon_dioxide").state == "494"
    assert hass.states.get("sensor.capteur_chambre_air_quality").state == "fine"

    assert hass.states.get("binary_sensor.detecteur_fumee").state == "off"
    assert hass.states.get("binary_sensor.detecteur_co").state == "off"
    assert hass.states.get("sensor.detecteur_fumee_battery").state == "88"
    assert hass.states.get("sensor.detecteur_co_carbon_monoxide_level").state == "ok"
    # Gateways are devices, not entities.
    assert hass.states.get("switch.legrand_gateway") is None


async def test_shutter_command(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    credentials,
    config_entry: MockConfigEntry,
) -> None:
    """Opening a shutter sends target_position 100 through its gateway."""
    mock_api(aioclient_mock)
    await _setup(hass, config_entry)

    await hass.services.async_call(
        "cover", "open_cover", {"entity_id": "cover.volet_salon"}, blocking=True
    )
    body = [
        call for call in aioclient_mock.mock_calls if str(call[1]).endswith("setstate")
    ][-1][2]
    assert body == {
        "home": {
            "id": "home-1",
            "modules": [{"id": SHUTTER, "target_position": 100, "bridge": NBG}],
        }
    }
    assert hass.states.get("cover.volet_salon").state == "opening"


@pytest.mark.parametrize(("code", "fails"), [(6, True), (23, False)])
async def test_command_module_errors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    credentials,
    config_entry: MockConfigEntry,
    code: int,
    fails: bool,
) -> None:
    """An HTTP 200 with module errors fails, except "already in that state"."""
    mock_api(aioclient_mock)
    await _setup(hass, config_entry)
    aioclient_mock.clear_requests()
    mock_api(aioclient_mock)
    aioclient_mock.post(
        f"{API_URL}/setstate",
        json={"status": "ok", "body": {"errors": [{"id": "x", "code": code}]}},
    )
    aioclient_mock._mocks.reverse()  # the module-error answer must win

    call = hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.prise_sejour"}, blocking=True
    )
    if fails:
        with pytest.raises(HomeAssistantError):
            await call
    else:
        await call


async def test_recent_alarms_shown_at_start(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    credentials,
    config_entry: MockConfigEntry,
) -> None:
    """A smoke detection from 2 minutes ago and a CO alarm are on after a restart."""
    mock_api(
        aioclient_mock,
        event_list=events((NSD, "smoke", 1, 120), (NCO, "co_detected", 2, 60)),
    )
    await _setup(hass, config_entry)

    smoke = hass.states.get("binary_sensor.detecteur_fumee")
    assert smoke.state == "on"
    assert smoke.attributes["last_event"] == "smoke"
    assert hass.states.get("binary_sensor.detecteur_co").state == "on"
    assert hass.states.get("sensor.detecteur_co_carbon_monoxide_level").state == "alarm"


async def test_cleared_and_old_alarms_are_off(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    credentials,
    config_entry: MockConfigEntry,
) -> None:
    """A cleared smoke event and an hour-old CO alarm leave both sensors off."""
    mock_api(
        aioclient_mock,
        event_list=events(
            (NSD, "smoke", 1, 300),
            (NSD, "smoke", 0, 200),
            (NCO, "co_detected", 2, 3600),
        ),
    )
    await _setup(hass, config_entry)

    assert hass.states.get("binary_sensor.detecteur_fumee").state == "off"
    assert hass.states.get("binary_sensor.detecteur_co").state == "off"


async def test_throttled_setup_retries(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    credentials,
    config_entry: MockConfigEntry,
) -> None:
    """A rate-limit answer makes Home Assistant retry instead of failing."""
    aioclient_mock.get(
        f"{API_URL}/homesdata",
        status=403,
        json={"error": {"code": 26, "message": "User usage reached"}},
    )
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_refused_refresh_retries_before_reauth(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    credentials,
    config_entry: MockConfigEntry,
) -> None:
    """One refused token refresh (Netatmo outage) retries, it does not ask to log in."""
    config_entry.data["token"]["expires_at"] = time.time() - 10
    aioclient_mock.post(OAUTH2_TOKEN, status=400, json={"error": "invalid_grant"})
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert not hass.config_entries.flow.async_progress()


async def test_offline_module_unavailable(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    credentials,
    config_entry: MockConfigEntry,
) -> None:
    """A gateway reported offline makes its shutters unavailable."""
    status = homestatus()
    modules = status["body"]["home"]["modules"]
    status["body"]["home"]["modules"] = [m for m in modules if m["id"] != NBG]
    status["body"]["home"]["errors"] = [{"id": NBG, "code": 6}]
    mock_api(aioclient_mock, status=status)
    await _setup(hass, config_entry)
    assert hass.states.get("cover.volet_salon").state == "unavailable"
    assert hass.states.get("switch.prise_sejour").state == "on"


async def test_diagnostics_redact_tokens(
    hass: HomeAssistant,
    hass_client,
    aioclient_mock: AiohttpClientMocker,
    credentials,
    config_entry: MockConfigEntry,
) -> None:
    """Diagnostics never contain the tokens."""
    mock_api(aioclient_mock)
    await _setup(hass, config_entry)
    diag = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)
    assert diag["entry"]["data"]["token"] == "**REDACTED**"
    assert "client-secret" not in str(diag)
    assert diag["raw"]["homesdata"][0]["name"] == "Maison"


async def test_shutter_followed_until_it_stops(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    credentials,
    config_entry: MockConfigEntry,
) -> None:
    """After a command, the state is read again until the shutter reports it."""
    mock_api(aioclient_mock)
    await _setup(hass, config_entry)

    await hass.services.async_call(
        "cover", "open_cover", {"entity_id": "cover.volet_salon"}, blocking=True
    )
    assert hass.states.get("cover.volet_salon").state == "opening"

    # 5 s later Netatmo still reports the old position: keep "opening".
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=6))
    await hass.async_block_till_done()
    assert hass.states.get("cover.volet_salon").state == "opening"

    # The shutter reaches the top: the next follow-up read shows it open.
    aioclient_mock.clear_requests()
    mock_api(aioclient_mock, status=homestatus(shutter_position=100))
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=17))
    await hass.async_block_till_done()
    assert hass.states.get("cover.volet_salon").state == "open"
    reads = len(aioclient_mock.mock_calls)

    # No more follow-up reads once the shutter has stopped.
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=40))
    await hass.async_block_till_done()
    assert len(aioclient_mock.mock_calls) == reads
