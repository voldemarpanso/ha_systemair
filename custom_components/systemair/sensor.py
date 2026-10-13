"""Sensors for Systemair."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    REVOLUTIONS_PER_MINUTE,
    UnitOfElectricPotential,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import SystemairConfigEntry
from .alarms import alarm_log
from .config_registers import output_connected
from .const import PARTS_PER_MILLION, SAVECONNECT_AIR_QUALITY
from .device import SystemairDevice, option_keys
from .entity import SystemairEntity


@dataclass(frozen=True, kw_only=True)
class SystemairSensorEntityDescription(SensorEntityDescription):
    value_fn: Callable[[SystemairDevice], Any]
    # Sensors fed by a configurable input are only available while an input is set up for them.
    available_fn: Callable[[SystemairDevice], bool] | None = None
    # Register whose options are the states of an enum sensor.
    options_register: str | None = None
    # Enabled by default when this holds at setup (instead of entity_registry_enabled_default).
    enabled_fn: Callable[[SystemairDevice], bool] | None = None


def tenths(register: str) -> Callable[[SystemairDevice], float | None]:
    def value(device: SystemairDevice) -> float | None:
        raw = device.int_value(register)
        return None if raw is None else raw / 10
    return value


def option(register: str) -> Callable[[SystemairDevice], str | None]:
    """Translated label of the register's current option (for attributes)."""
    def value(device: SystemairDevice) -> str | None:
        title = device.option_title(register)
        return None if title is None else device.translate(title)
    return value


def component(key: str, name: str, register: str, icon: str) -> SystemairSensorEntityDescription:
    """Enum sensor of a component setting; states are stable option keys, labels come from the translations."""
    return SystemairSensorEntityDescription(
        key=key,
        name=name,
        icon=icon,
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENUM,
        value_fn=lambda device: device.option_state(register),
        options_register=register,
    )


def air_quality(device: SystemairDevice) -> str | None:
    level = device.int_value("REG_IAQ_LEVEL")
    return SAVECONNECT_AIR_QUALITY[level] if level is not None and level < len(SAVECONNECT_AIR_QUALITY) else None


def filter_remaining_percent(device: SystemairDevice) -> int | None:
    remaining = device.int_value("REG_FILTER_REMAINING_TIME_L")
    period_months = device.int_value("REG_FILTER_PERIOD")
    if remaining is None or not period_months:
        return None
    return int(remaining / (period_months * 30 * 24 * 3600) * 100)


def humidity_inputs(device: SystemairDevice) -> int | None:
    """Highest reading of the humidity sensors on universal inputs.

    REG_SENSOR_RHS_n is assumed to belong to universal input n.
    """
    values = [device.int_value(f"REG_SENSOR_RHS_{n}") for n in device.universal_inputs("RH")]
    values = [v for v in values if v is not None]
    return max(values) if values else None


def temperature(key: str, name: str, register: str, **kwargs) -> SystemairSensorEntityDescription:
    return SystemairSensorEntityDescription(
        key=key,
        name=name,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=tenths(register),
        **kwargs,
    )



FAN_LEVELS = ("MIN", "LOW", "NORMAL", "HIGH", "MAX")


def fan_level(fan: str, level: str) -> SystemairSensorEntityDescription:
    """Fan output (%) the unit uses for an airflow level; an installer setting, shown read-only."""
    level_name = {"MIN": "Minimum", "MAX": "Maximum"}.get(level, level.capitalize())
    return SystemairSensorEntityDescription(
        key=f"fan_level_{fan.lower()}_{level.lower()}",
        name=f"{level_name} level {'supply' if fan == 'SAF' else 'extract'} airflow",
        icon="mdi:fan",
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: device.int_value(f"REG_FAN_LEVEL_{fan}_{level}_PERCENTAGE"),
    )


def analog_output(n: int) -> SystemairSensorEntityDescription:
    """Level of analog output n (0-10 V); enabled by default when the output has a function."""
    return SystemairSensorEntityDescription(
        key=f"analog_output_{n}",
        name=f"Analog Output {n}",
        icon="mdi:sine-wave",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=tenths(f"REG_OUTPUT_AO{n}"),
        enabled_fn=output_connected(f"REG_AO_CFG_CONNECTION_{n}"),
    )

# Keys are part of the unique ids and must not change.
SENSORS: tuple[SystemairSensorEntityDescription, ...] = (
    SystemairSensorEntityDescription(
        key="internal_relative_humidity",
        name="Extract Air Relative Humidity",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: device.int_value("REG_SENSOR_RHS_PDM"),
    ),
    temperature("internal_extract_temperature", "Internal Extract Temperature", "REG_SENSOR_PDM_EAT_VALUE"),
    temperature("outdoor_temperature", "Outdoor Temperature", "REG_SENSOR_OAT"),
    temperature("overheating_temperature", "Overheating Temperature", "REG_SENSOR_OHT",
                entity_category=EntityCategory.DIAGNOSTIC),
    temperature("supply_temperature", "Supply Temperature", "REG_SENSOR_SAT"),
    temperature("efficiency_temperature", "Efficiency Temperature", "REG_SENSOR_EFT"),
    temperature("room_temperature", "Room Temperature", "REG_SENSOR_RAT",
                available_fn=lambda device: device.has_temperature_input("RAT")),
    temperature("extract_temperature", "Extract Temperature", "REG_SENSOR_EAT",
                available_fn=lambda device: device.has_temperature_input("EAT")),
    temperature("extra_controller_temperature", "Extra Controller Temperature", "REG_SENSOR_ECT",
                entity_category=EntityCategory.DIAGNOSTIC,
                available_fn=lambda device: device.has_temperature_input("ECT")),
    temperature("frost_protection_temperature", "Frost Protection Temperature", "REG_SENSOR_FPT",
                entity_category=EntityCategory.DIAGNOSTIC,
                available_fn=lambda device: device.has_temperature_input("FTP")),
    SystemairSensorEntityDescription(
        key="supply_air_fan_speed",
        name="Supply Air Fan Speed",
        icon="mdi:fan",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=REVOLUTIONS_PER_MINUTE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: device.int_value("REG_SENSOR_RPM_SAF"),
    ),
    SystemairSensorEntityDescription(
        key="extract_air_fan_speed",
        name="Extract Air Fan Speed",
        icon="mdi:fan",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=REVOLUTIONS_PER_MINUTE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: device.int_value("REG_SENSOR_RPM_EAF"),
    ),
    SystemairSensorEntityDescription(
        key="co2_sensor",
        name="CO2 Sensor",
        native_unit_of_measurement=PARTS_PER_MILLION,
        device_class=SensorDeviceClass.CO2,
        state_class=SensorStateClass.MEASUREMENT,
        # The unit's combined CO2 value from all inputs configured as CO2 sensors.
        value_fn=lambda device: device.int_value("REG_SENSOR_CO2S"),
        available_fn=lambda device: bool(device.universal_inputs("CO2")),
    ),
    SystemairSensorEntityDescription(
        key="room_relative_humidity",
        name="Room Relative Humidity",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=humidity_inputs,
        available_fn=lambda device: bool(device.universal_inputs("RH")),
    ),
    SystemairSensorEntityDescription(
        key="air_quality",
        name="Air Quality",
        icon="mdi:leaf",
        device_class=SensorDeviceClass.ENUM,
        options=SAVECONNECT_AIR_QUALITY,
        value_fn=air_quality,
    ),
    SystemairSensorEntityDescription(
        key="filter_remaining_time",
        name="Filter Time Remaining",
        icon="mdi:air-filter",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.DAYS,
        suggested_display_precision=0,
        device_class=SensorDeviceClass.DURATION,
        value_fn=lambda device: device.int_value("REG_FILTER_REMAINING_TIME_L"),
    ),
    SystemairSensorEntityDescription(
        key="preset_remaining_time",
        name="Preset Time Remaining",
        icon="mdi:timer-sand",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        device_class=SensorDeviceClass.DURATION,
        value_fn=lambda device: device.int_value("REG_USERMODE_REMAINING_TIME_L"),
    ),
    SystemairSensorEntityDescription(
        key="filter_remaining_percent",
        name="Filter Life Remaining",
        icon="mdi:air-filter",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=filter_remaining_percent,
    ),
    component("components_heat_exchanger", "Heat Exchanger Type", "REG_HEAT_EXCHANGER_TYPE", "mdi:heat-wave"),
    component("components_heater", "Heater", "REG_UNIT_CONFIG_REHEATER_TYPE", "mdi:heating-coil"),
    component("components_cooler", "Cooler", "REG_UNIT_CONFIG_COOLER", "mdi:snowflake"),
    component("components_extra_controller", "Extra Controller", "REG_UNIT_CONFIG_EXTRA_CONTROLLER", "mdi:plus"),
    SystemairSensorEntityDescription(
        key="fan_percentage_saf",
        name="Supply Fan Output",
        icon="mdi:fan",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: device.int_value("REG_OUTPUT_SAF"),
    ),
    SystemairSensorEntityDescription(
        key="fan_percentage_eaf",
        name="Extract Fan Output",
        icon="mdi:fan",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: device.int_value("REG_OUTPUT_EAF"),
    ),
    *(analog_output(n) for n in range(1, 6)),
    *(fan_level(fan, level) for level in FAN_LEVELS for fan in ("SAF", "EAF")),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: SystemairConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        [
            *(SystemairSensor(device, description) for device in entry.runtime_data.devices for description in SENSORS),
            *(SystemairWeekSchedule(device) for device in entry.runtime_data.devices),
            *(SystemairAlarmLog(device) for device in entry.runtime_data.devices),
        ]
    )


class SystemairSensor(SystemairEntity, SensorEntity):
    entity_description: SystemairSensorEntityDescription

    def __init__(self, device: SystemairDevice, description: SystemairSensorEntityDescription) -> None:
        super().__init__(device, description.key)
        self.entity_description = description
        if description.enabled_fn is not None:
            self._attr_entity_registry_enabled_default = description.enabled_fn(device)

    @property
    def available(self) -> bool:
        available_fn = self.entity_description.available_fn
        return super().available and (available_fn is None or available_fn(self._device))

    @property
    def options(self) -> list[str] | None:
        if register := self.entity_description.options_register:
            reg = self._device.register(register)
            return list(option_keys(reg.options if reg else None))
        return super().options

    @property
    def native_unit_of_measurement(self) -> str | None:
        if self.entity_description.device_class == SensorDeviceClass.TEMPERATURE:
            return self._device.temperature_unit
        return super().native_unit_of_measurement

    @property
    def native_value(self):
        return self.entity_description.value_fn(self._device)


WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _time(value) -> str | None:
    hour, minute = getattr(value, "hour", None), getattr(value, "minute", None)
    return None if hour is None or minute is None else f"{hour:02d}:{minute:02d}"


def week_schedule(device: SystemairDevice) -> dict[str, list[str]]:
    """Enabled periods per day as "HH:MM-HH:MM"; 00:00-00:00 is an unused period. Day 1 is Monday."""
    schedule = {}
    for day, name in enumerate(WEEKDAYS, start=1):
        periods = []
        for period in (1, 2):
            prefix = f"REG_WS_DAY{day}_PRD{period}"
            start, end = _time(device.value(f"{prefix}_START_H")), _time(device.value(f"{prefix}_END_H"))
            if device.bool_value(f"{prefix}_ENABLED") and start and end and not start == end == "00:00":
                periods.append(f"{start}-{end}")
        schedule[name] = periods
    return schedule


WEEK_SCHEDULE = SensorEntityDescription(
    key="week_schedule",
    name="Week schedule",
    icon="mdi:calendar-clock",
    entity_category=EntityCategory.DIAGNOSTIC,
    native_unit_of_measurement="periods",
)


class SystemairWeekSchedule(SystemairEntity, SensorEntity):
    """The unit's week schedule, read-only: number of periods, with the periods per day as attributes."""

    entity_description = WEEK_SCHEDULE

    def __init__(self, device: SystemairDevice) -> None:
        super().__init__(device, WEEK_SCHEDULE.key)
        # Read the registry directly so the schedule registers are polled only when the entity is enabled.
        defined = getattr(device.registry, "REG_WS_ANY_DEFINED", None)
        self._attr_entity_registry_enabled_default = bool(defined and str(defined.value).lower() in ("true", "1"))

    @property
    def native_value(self) -> int:
        return sum(len(periods) for periods in week_schedule(self._device).values())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        device = self._device
        level = option("REG_WS_FAN_LEVEL_SCHEDULED")(device)
        unscheduled = option("REG_WS_FAN_LEVEL_UNSCHEDULED")(device)
        offset_active = device.int_value("REG_WS_T_OFFSET_ACTIVE")
        offset_inactive = device.int_value("REG_WS_T_OFFSET_INACTIVE")
        return {
            **week_schedule(device),
            "scheduled_airflow": level,
            "unscheduled_airflow": unscheduled,
            "scheduled_temperature_offset": None if offset_active is None else offset_active / 10,
            "unscheduled_temperature_offset": None if offset_inactive is None else offset_inactive / 10,
        }


ALARM_LOG = SensorEntityDescription(
    key="alarm_log",
    name="Alarm log",
    icon="mdi:alarm-light-outline",
    device_class=SensorDeviceClass.TIMESTAMP,
    entity_category=EntityCategory.DIAGNOSTIC,
)


class SystemairAlarmLog(SystemairEntity, SensorEntity):
    """Time of the unit's latest alarm log entry, with the latest entries as attributes."""

    entity_description = ALARM_LOG

    def __init__(self, device: SystemairDevice) -> None:
        super().__init__(device, ALARM_LOG.key)

    def _entries(self):
        return alarm_log(self._device.registry, dt_util.get_default_time_zone())

    @property
    def native_value(self):
        entries = self._entries()
        return entries[0].time if entries else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"entries": [str(entry) for entry in self._entries()]}
