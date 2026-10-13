"""The unit's alarms and alarm log."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Any

ALARM_ACTIVE = 1

ALARMS = {
    "REG_ALARM_SAF_CTRL_ALARM": "Supply Air Fan Control",
    "REG_ALARM_EAF_CTRL_ALARM": "Extract Air Fan Control",
    "REG_ALARM_FROST_PROT_ALARM": "Frost Protection",
    "REG_ALARM_DEFROSTING_ALARM": "Defrosting Malfunction",
    "REG_ALARM_SAF_RPM_ALARM": "Supply Air Fan RPM",
    "REG_ALARM_EAF_RPM_ALARM": "Extract Air Fan RPM",
    "REG_ALARM_FPT_ALARM": "Frost Protection Sensor",
    "REG_ALARM_OAT_ALARM": "Outdoor Air Temperature Sensor",
    "REG_ALARM_SAT_ALARM": "Supply Air Temperature Sensor",
    "REG_ALARM_RAT_ALARM": "Room Air Temperature Sensor",
    "REG_ALARM_EAT_ALARM": "Extract Air Temperature Sensor",
    "REG_ALARM_ECT_ALARM": "Extra Controller Temperature Sensor",
    "REG_ALARM_EFT_ALARM": "Efficiency Temperature Sensor",
    "REG_ALARM_OHT_ALARM": "Overheat Temperature Sensor",
    "REG_ALARM_EMT_ALARM": "Emergency Thermostat",
    "REG_ALARM_RGS_ALARM": "Rotor Guard",
    "REG_ALARM_BYS_ALARM": "Bypass Damper",
    "REG_ALARM_SECONDARY_AIR_ALARM": "Secondary Air Damper",
    "REG_ALARM_FILTER_ALARM": "Filter Change",
    "REG_ALARM_EXTRA_CONTROLLER_ALARM": "Extra Controller",
    "REG_ALARM_EXTERNAL_STOP_ALARM": "External Stop",
    "REG_ALARM_RH_ALARM": "Relative Humidity Sensor",
    "REG_ALARM_CO2_ALARM": "CO2 Sensor",
    "REG_ALARM_LOW_SAT_ALARM": "Low Supply Air Temperature",
    "REG_ALARM_BYF_ALARM": "Bypass Damper Feedback",
    "REG_ALARM_PDM_RHS_ALARM": "Built-in Humidity Sensor",
    "REG_ALARM_PDM_EAT_ALARM": "Built-in Extract Air Temperature Sensor",
    "REG_ALARM_MANUAL_FAN_STOP_ALARM": "Manual Fan Stop",
    "REG_ALARM_OVERHEAT_TEMPERATURE_ALARM": "Overheat Temperature",
    "REG_ALARM_FIRE_ALARM_ALARM": "Fire Alarm",
    "REG_ALARM_FILTER_WARNING_ALARM": "Filter Warning",
    "REG_ALARM_MANUAL_OVERRIDE_OUTPUTS_ALARM": "Output in Manual Mode",
}

# REG_ALARM_*_ALARM and REG_ALARM_LOG_*_STATE_* values.
ALARM_STATES = ("inactive", "active", "waiting", "acknowledged")

# Alarm names by REG_ALARM_LOG_*_ID value (SaveConnect's English labels). The
# unit's metadata leaves 28 without a title; it is "Output in manual mode"
# (REG_ALARM_MANUAL_OVERRIDE_OUTPUTS_ALARM; confirmed by setting an output to manual).
LOG_ALARMS = (
    "Frost protection", "Frost protection temperature sensor", "Defrosting error", "Supply air fan rpm",
    "Extract air fan rpm", "Supply air fan control error", "Extract air fan control error", "Emergency thermostat",
    "Bypass damper", "Rotor guard", "Secondary air damper", "Outdoor air temperature sensor",
    "Overheat temperature sensor", "Supply air temperature sensor", "Room air temperature sensor",
    "Extract air temperature sensor", "Extra controller temperature sensor", "Efficiency temperature sensor",
    "Built-in RH sensor", "Built-in extract air temperature sensor", "Filter", "Extra controller alarm",
    "External stop", "Manual fan stop", "Overheat alarm", "Low supply air temperature", "CO2 sensor",
    "External RH sensor", "Output in manual mode", "Fire", "Filter warning", "Communication fault", "Fault code",
    "Rotor motor feedback", "Bypass damper feedback", "Heater malfunction",
)

# The unit keeps 20 entries, newest first; this many are shown.
LOG_SIZE = 10
LOG_FIELDS = ("ID", "STATE_NOW", "STATE_PREVIOUS", "YEAR", "MONTH", "DAY", "HOUR", "MINUTE", "SECOND")
LOG_REGISTERS = tuple(f"REG_ALARM_LOG_{n}_{field}" for n in range(1, LOG_SIZE + 1) for field in LOG_FIELDS)


@dataclass(frozen=True)
class LogEntry:
    time: datetime
    alarm: str
    state: str
    previous_state: str

    def __str__(self) -> str:
        return f"{self.time:%Y-%m-%d %H:%M} {self.alarm}: {self.previous_state} → {self.state}"


def _int(registry: Any, name: str) -> int | None:
    reg = getattr(registry, name, None)
    try:
        return int(float(reg.value))
    except (AttributeError, TypeError, ValueError):
        return None


def _state(value: int | None) -> str:
    return ALARM_STATES[value] if value is not None and 0 <= value < len(ALARM_STATES) else f"state {value}"


def alarm_log(registry: Any, tz: tzinfo) -> list[LogEntry]:
    """The latest LOG_SIZE entries, newest first; empty slots are left out.

    The unit stores local time with a two-digit year. Reads the registry
    directly, so the log registers are not added to the regular poll.
    """
    entries = []
    for n in range(1, LOG_SIZE + 1):
        values = {field: _int(registry, f"REG_ALARM_LOG_{n}_{field}") for field in LOG_FIELDS}
        if any(value is None for value in values.values()):
            continue
        try:
            time = datetime(2000 + values["YEAR"], values["MONTH"], values["DAY"],
                            values["HOUR"], values["MINUTE"], values["SECOND"], tzinfo=tz)
        except ValueError:  # unused slot (zeros)
            continue
        alarm_id = values["ID"]
        alarm = LOG_ALARMS[alarm_id] if 0 <= alarm_id < len(LOG_ALARMS) else f"Alarm {alarm_id}"
        entries.append(LogEntry(time, alarm, _state(values["STATE_NOW"]), _state(values["STATE_PREVIOUS"])))
    return entries


def alarm_states(registry: Any) -> tuple[int | None, ...]:
    """Raw state of every alarm, to notice when the log has new entries."""
    return tuple(_int(registry, register) for register in ALARMS)
