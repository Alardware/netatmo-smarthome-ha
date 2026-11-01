"""Constants for the Netatmo Smart Home integration."""

from __future__ import annotations

from datetime import timedelta
import logging

DOMAIN = "netatmo_smarthome"
LOGGER = logging.getLogger(__package__)

ATTRIBUTION = "Data provided by the Netatmo cloud (unofficial integration)"

OAUTH2_AUTHORIZE = "https://api.netatmo.com/oauth2/authorize"
OAUTH2_TOKEN = "https://api.netatmo.com/oauth2/token"
API_URL = "https://api.netatmo.com/api"

# Home + Control (Legrand, Bubendorff), Home Coach and Home Security alarms.
SCOPES = [
    "read_magellan",
    "write_magellan",
    "read_bubendorff",
    "write_bubendorff",
    "read_homecoach",
    "read_smokedetector",
    "read_carbonmonoxidedetector",
]

# Netatmo allows about 500 requests per hour and per user: one cycle costs
# one homestatus and one getevents per home, plus Home Coach every 5 cycles.
DEFAULT_SCAN_INTERVAL = 60
MIN_SCAN_INTERVAL = 30
MAX_SCAN_INTERVAL = 600
HOMECOACH_EVERY = 5
TOPOLOGY_INTERVAL = timedelta(hours=6)
THROTTLE_DELAY = 15 * 60
# Seconds before reading the state back after a command, then while a shutter
# is still moving: every FOLLOW_UP_INTERVAL seconds, at most FOLLOW_UP_MAX times.
REFRESH_AFTER_COMMAND = 5
FOLLOW_UP_INTERVAL = 10
FOLLOW_UP_MAX = 8
# Consecutive token refresh rejections before asking the user to log in again
# (Netatmo sometimes answers 400 during outages).
MAX_TOKEN_FAILURES = 3

# How long a smoke or CO detection stays on without a "cleared" event.
ALARM_TIMEOUT = timedelta(minutes=30)

# Module types (see pyatmo and the Netatmo API documentation).
GATEWAY_TYPES = {"NLG", "NLGS", "NBG"}
SWITCH_TYPES = {
    "NLP",
    "NLPM",
    "NLPBS",
    "NLC",
    "NLUP",
    "NLUI",
    "NLPT",
    "NLPO",
    "NLPD",
}
OUTLET_TYPES = {"NLP", "NLPM", "NLPBS", "NLC", "NLUP"}
LIGHT_TYPES = {"NLM", "NLL", "NLIS"}
DIMMER_TYPES = {"NLF", "NLFN", "NLFE", "NLUF", "NLUO", "Z3L"}
COVER_TYPES = {"NLV", "NLLV", "NLLM", "NLIV", "Z3V", "NBR", "NBO", "NBS"}
GARAGE_TYPES = {"NLJ"}
METER_TYPES = {"NLPC", "NLPS", "NLY"}
SMOKE_TYPES = {"NSD"}
CO_TYPES = {"NCO"}
HOMECOACH_TYPES = {"NHC"}

MODEL_NAMES = {
    "NLG": "Legrand Gateway",
    "NLGS": "Legrand Gateway",
    "NBG": "Bubendorff iDiamant",
    "NBR": "Bubendorff roller shutter",
    "NBO": "Bubendorff orientable shutter",
    "NBS": "Bubendorff swing shutter",
    "NLP": "Legrand connected outlet",
    "NLPM": "Legrand mobile outlet",
    "NLC": "Legrand cable outlet",
    "NLM": "Legrand light micromodule",
    "NLIS": "Legrand double switch",
    "NLV": "Legrand roller shutter switch",
    "NHC": "Healthy Home Coach",
    "NSD": "Smart Smoke Alarm",
    "NCO": "Smart Carbon Monoxide Alarm",
}

# Home Coach health index (health_idx).
HEALTH_LEVELS = ["healthy", "fine", "fair", "poor", "unhealthy"]
# CO alarm sub_type.
CO_LEVELS = {0: "ok", 1: "pre_alarm", 2: "alarm"}
