"""Setup, entities, commands, alarms and diagnostics tests."""

from __future__ import annotations

from datetime import timedelta
import time

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)
from yarl import URL

from custom_components.netatmo_smarthome.const import API_URL, DOMAIN, OAUTH2_TOKEN

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
    assert cover.attributes["current_position"] == 0

    assert hass.states.get("sensor.capteur_chambre_temperature").state == "20.3"
    assert hass.states.get("sensor.capteur_chambre_carbon_dioxide").state == "494"
    assert hass.states.get("sensor.capteur_chambre_air_quality").state == "fine"

    assert hass.states.get("binary_sensor.detecteur_fumee").state == "off"
    assert hass.states.get("binary_sensor.detecteur_co").state == "off"
    # Alarms report no battery, only their last monthly contact.
    assert hass.states.get("sensor.detecteur_fumee_battery") is None
    assert (
        hass.states.get("sensor.detecteur_fumee_last_contact").state
        == "2026-09-21T14:13:20+00:00"
    )
    # A sleeping remote (reachable: false) still shows its battery.
    assert hass.states.get("sensor.commande_sans_fil_battery").state == "50"
    assert hass.states.get("sensor.detecteur_co_carbon_monoxide_level").state == "ok"
    # Gateways are devices (parents of their modules), not entities.
    assert hass.states.get("switch.legrand_gateway") is None
    registry = dr.async_get(hass)
    gateway = registry.async_get_device(identifiers={(DOMAIN, NBG)})
    shutter = registry.async_get_device(identifiers={(DOMAIN, SHUTTER)})
    assert gateway is not None and shutter.via_device_id == gateway.id


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


async def test_shutter_position_and_fixed_steps(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    credentials,
    config_entry: MockConfigEntry,
) -> None:
    """A positionable shutter takes a position; a step-100 one shows none."""
    mock_api(aioclient_mock)
    await _setup(hass, config_entry)
    await hass.services.async_call(
        "cover",
        "set_cover_position",
        {"entity_id": "cover.volet_salon", "position": 42},
        blocking=True,
    )
    body = [c for c in aioclient_mock.mock_calls if str(c[1]).endswith("setstate")][-1][
        2
    ]
    assert body["home"]["modules"][0]["target_position"] == 42


async def test_shutter_without_positioning(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    credentials,
    config_entry: MockConfigEntry,
) -> None:
    """Shutters with a step of 100 only open, close and stop."""
    mock_api(aioclient_mock, status=homestatus(step=100))
    await _setup(hass, config_entry)
    cover = hass.states.get("cover.volet_salon")
    assert cover.state == "closed"
    assert "current_position" not in cover.attributes


async def test_saved_token_does_not_reload(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    credentials,
    config_entry: MockConfigEntry,
) -> None:
    """Saving a refreshed token (every 3 hours) must not reload the entry."""
    mock_api(aioclient_mock)
    await _setup(hass, config_entry)
    homesdata_calls = sum(
        str(c[1]).endswith("homesdata") for c in aioclient_mock.mock_calls
    )

    token = {
        **config_entry.data["token"],
        "access_token": "new",
        "refresh_token": "new",
    }
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, "token": token}
    )
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert (
        sum(str(c[1]).endswith("homesdata") for c in aioclient_mock.mock_calls)
        == homesdata_calls
    )
    assert hass.states.get("cover.volet_salon").state == "closed"


async def test_transient_failures_keep_last_values(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    credentials,
    config_entry: MockConfigEntry,
) -> None:
    """Two failed updates keep the last values; the third one gives up."""
    mock_api(aioclient_mock)
    await _setup(hass, config_entry)
    coordinator = config_entry.runtime_data

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API_URL}/homestatus", status=500, text="error")
    for _ in range(2):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get("cover.volet_salon").state == "closed"
        assert hass.states.get("sensor.capteur_chambre_temperature").state == "20.3"

    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("cover.volet_salon").state == "unavailable"


async def test_busy_netatmo_is_retried(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    credentials,
    config_entry: MockConfigEntry,
) -> None:
    """A 503 "service temporarily unavailable" is retried once, unnoticed."""
    mock_api(aioclient_mock)
    answers = iter(
        [
            AiohttpClientMockResponse(
                "GET",
                URL(f"{API_URL}/homestatus"),
                status=503,
                json={
                    "error": {"code": 27, "message": "Service temporarily unavailable"}
                },
            ),
            AiohttpClientMockResponse(
                "GET", URL(f"{API_URL}/homestatus"), json=homestatus()
            ),
        ]
    )

    async def _homestatus(method, url, data):
        return next(answers)

    aioclient_mock._mocks.insert(
        0,
        AiohttpClientMockResponse(
            "GET", URL(f"{API_URL}/homestatus"), side_effect=_homestatus
        ),
    )
    await _setup(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("cover.volet_salon").state == "closed"


async def test_failures_slow_polling_down(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    credentials,
    config_entry: MockConfigEntry,
) -> None:
    """Each failed update doubles the interval; a success restores it."""
    mock_api(aioclient_mock)
    await _setup(hass, config_entry)
    coordinator = config_entry.runtime_data
    assert coordinator.update_interval == timedelta(seconds=60)

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API_URL}/homestatus", status=503, text="busy")
    await coordinator.async_refresh()
    assert coordinator.update_interval == timedelta(seconds=120)
    await coordinator.async_refresh()
    assert coordinator.update_interval == timedelta(seconds=240)

    aioclient_mock.clear_requests()
    mock_api(aioclient_mock)
    await coordinator.async_refresh()
    assert coordinator.update_interval == timedelta(seconds=60)
