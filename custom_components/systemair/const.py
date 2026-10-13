"""Constants for the Systemair integration."""
from datetime import timedelta

from .saveconnect.const import UserPresets

try:
    from homeassistant.const import UnitOfRatio

    PARTS_PER_MILLION = UnitOfRatio.PARTS_PER_MILLION
except ImportError:  # Home Assistant before UnitOfRatio
    from homeassistant.const import CONCENTRATION_PARTS_PER_MILLION as PARTS_PER_MILLION

DOMAIN = "systemair"
ISSUE_TRACKER = "https://github.com/voldemarpanso/ha_systemair/issues"
MANUFACTURER = "Systemair"

HA_SC_CLOUD_PUSH = "cloud_push"
HA_SC_CLOUD_PUSH_DEFAULT = False

# Prefix of entity unique ids; kept so existing entities keep their history.
SAVECONNECT_NAME = "SAVE Connect"

# Poll of the registers entities use. SaveConnect does not push register
# values over the websocket, so this runs whether or not it is connected.
# Each poll is one request the cloud relays to the unit; a burst of ~100
# requests in a couple of minutes once took the unit offline for a while.
CONF_SCAN_INTERVAL = "scan_interval"
SCAN_INTERVAL = timedelta(seconds=60)
MIN_SCAN_INTERVAL = 20
MAX_SCAN_INTERVAL = 600
# Read of every register (about 0.5 MB), to pick up configuration changes.
FULL_READ_INTERVAL = timedelta(minutes=30)
# How often device status (online, update in progress) is fetched.
ACCOUNT_REFRESH_INTERVAL = timedelta(minutes=10)

# REG_SPEED_INDICATION_APP values.
AIRFLOW_LEVELS = ["Off", "Minimum", "Low", "Normal", "High", "Maximum", "Demand", "External"]

# REG_USERMODE_MODE_HMI values, in order.
PRESETS = {
    "Auto": UserPresets.AUTO,
    "Manual": UserPresets.MANUAL,
    "Crowded": UserPresets.CROWDED,
    "Refresh": UserPresets.REFRESH,
    "Fireplace": UserPresets.FIREPLACE,
    "Away": UserPresets.AWAY,
    "Holiday": UserPresets.HOLIDAY,
}

SAVECONNECT_AIR_QUALITY = ["Economic", "Good", "Improving"]
