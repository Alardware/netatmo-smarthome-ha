"""Fixtures for the Netatmo Smart Home tests (payload shapes from pyatmo)."""

from __future__ import annotations

import time
from typing import Any

from homeassistant.components.application_credentials import (
    ClientCredential,
    async_import_client_credential,
)
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.netatmo_smarthome.const import API_URL, DOMAIN, SCOPES

HOME = "home-1"
NLG, PLUG, GANG1 = "70:ee:50:00:00:01", "00:04:74:00:00:02", "00:04:74:00:00:03#1"
NBG, SHUTTER = "70:ee:50:00:00:04", "0009999992"
NSD, NCO, COACH = "70:ee:50:00:00:05", "70:ee:50:00:00:06", "70:ee:50:00:00:07"
REMOTE = "00:04:74:00:00:08"

HOMESDATA = {
    "status": "ok",
    "body": {
        "homes": [
            {
                "id": HOME,
                "name": "Maison",
                "rooms": [{"id": "r1", "name": "Séjour"}],
                "modules": [
                    {"id": NLG, "type": "NLG", "name": "Legrand Gateway"},
                    {
                        "id": PLUG,
                        "type": "NLP",
                        "name": "Prise Séjour",
                        "bridge": NLG,
                        "room_id": "r1",
                    },
                    {"id": GANG1, "type": "NLIS", "name": "Applique", "bridge": NLG},
                    {"id": NBG, "type": "NBG", "name": "Bubendorff Gateway"},
                    {
                        "id": SHUTTER,
                        "type": "NBR",
                        "name": "Volet Salon",
                        "bridge": NBG,
                    },
                    {"id": NSD, "type": "NSD", "name": "Détecteur fumée"},
                    {"id": NCO, "type": "NCO", "name": "Détecteur CO"},
                    {
                        "id": REMOTE,
                        "type": "NLT",
                        "name": "Commande sans fil",
                        "bridge": NLG,
                    },
                ],
            }
        ]
    },
}


def homestatus(
    shutter_position: int = 0, plug_on: bool = True, step: int = 1
) -> dict[str, Any]:
    """Return a homestatus answer (shapes recorded from a real installation)."""
    return {
        "status": "ok",
        "body": {
            "home": {
                "id": HOME,
                "modules": [
                    {
                        "id": NLG,
                        "type": "NLG",
                        "reachable": True,
                        "firmware_revision": 211,
                    },
                    {
                        "id": PLUG,
                        "type": "NLP",
                        "on": plug_on,
                        "power": 120,
                        "reachable": True,
                        "bridge": NLG,
                    },
                    {"id": GANG1, "type": "NLIS", "on": False, "bridge": NLG},
                    {"id": NBG, "type": "NBG", "reachable": True},
                    {
                        "id": SHUTTER,
                        "type": "NBR",
                        "current_position": shutter_position,
                        "target_position": shutter_position,
                        "target_position:step": step,
                        "battery_level": 3,
                        "reachable": True,
                        "bridge": NBG,
                    },
                    {
                        "id": NSD,
                        "type": "NSD",
                        "last_seen": 1790000000,
                        "wifi_strength": 58,
                    },
                    {
                        "id": NCO,
                        "type": "NCO",
                        "last_seen": 1790000000,
                        "wifi_strength": 50,
                    },
                    {
                        "id": REMOTE,
                        "type": "NLT",
                        "battery_state": "medium",
                        "battery_level": 2400,
                        "last_seen": 0,
                        "reachable": False,
                        "bridge": NLG,
                    },
                ],
            }
        },
    }


def events(*items: tuple[str, str, int, int]) -> dict[str, Any]:
    """Return a getevents answer from (module, type, sub_type, seconds ago)."""
    now = int(time.time())
    return {
        "status": "ok",
        "body": {
            "home": {
                "id": HOME,
                "events": [
                    {
                        "id": f"e{i}",
                        "module_id": m,
                        "type": t,
                        "sub_type": s,
                        "time": now - ago,
                    }
                    for i, (m, t, s, ago) in enumerate(items)
                ],
            }
        },
    }


HOMECOACHS = {
    "status": "ok",
    "body": {
        "devices": [
            {
                "_id": COACH,
                "type": "NHC",
                "station_name": "Capteur Chambre",
                "reachable": True,
                "dashboard_data": {
                    "Temperature": 20.3,
                    "CO2": 494,
                    "Humidity": 63,
                    "Noise": 42,
                    "Pressure": 1014.5,
                    "health_idx": 1,
                },
            }
        ]
    },
}


def mock_api(
    aioclient_mock: AiohttpClientMocker,
    status: dict[str, Any] | None = None,
    event_list: dict[str, Any] | None = None,
) -> None:
    """Register the fake Netatmo API."""
    aioclient_mock.get(f"{API_URL}/homesdata", json=HOMESDATA)
    aioclient_mock.get(f"{API_URL}/homestatus", json=status or homestatus())
    aioclient_mock.get(f"{API_URL}/getevents", json=event_list or events())
    aioclient_mock.get(f"{API_URL}/gethomecoachsdata", json=HOMECOACHS)
    aioclient_mock.post(f"{API_URL}/setstate", json={"status": "ok"})


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests."""
    return


@pytest.fixture
async def credentials(hass: HomeAssistant) -> None:
    """Register the user's Netatmo app credentials."""
    assert await async_setup_component(hass, "application_credentials", {})
    await async_import_client_credential(
        hass, DOMAIN, ClientCredential("client-id", "client-secret"), DOMAIN
    )


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return a config entry with a valid token."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        title="Netatmo",
        data={
            "auth_implementation": DOMAIN,
            "token": {
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_at": time.time() + 3600,
                "scope": SCOPES,
            },
        },
    )
