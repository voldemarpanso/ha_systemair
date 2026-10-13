"""Unit settings exposed as select / number / switch entities.

The platform follows from the register metadata SaveConnect returns: a
register with options becomes a select (a switch when the options are just
off/on), a boolean a switch, an hour:minute value a time, and a number
with min/max a number entity. Registers the unit does not have, or that
are read-only, are skipped. To expose another setting, add a line here.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.const import (
    PERCENTAGE,
    REVOLUTIONS_PER_MINUTE,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolumeFlowRate,
)

from .const import PARTS_PER_MILLION
from .device import SystemairDevice
from .saveconnect.models import SaveConnectTime

# SaveConnect "unit" codes in register metadata (the web app's unit enum).
UNIT_CODES = {
    0: UnitOfElectricPotential.VOLT,
    1: UnitOfTime.SECONDS,
    2: UnitOfTime.MINUTES,
    4: UnitOfTemperature.KELVIN,
    5: UnitOfTemperature.CELSIUS,
    6: UnitOfTemperature.FAHRENHEIT,
    7: PERCENTAGE,
    8: PERCENTAGE,  # % RH
    9: PARTS_PER_MILLION,
    10: REVOLUTIONS_PER_MINUTE,
    11: UnitOfPressure.PA,
    12: "inWC",
    13: "L/s",
    14: UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
    15: UnitOfVolumeFlowRate.CUBIC_FEET_PER_MINUTE,
    16: "g/kg",
    17: UnitOfTime.HOURS,
    18: UnitOfTime.DAYS,
}


def _option_title(device: SystemairDevice, register: str) -> str | None:
    """Current option title, read without adding the register to the poll."""
    reg = getattr(device.registry, register, None)
    if reg is None or not reg.options:
        return None
    try:
        value = int(float(reg.value))
    except (TypeError, ValueError):
        return None
    return next((o.title for o in reg.options if o.value == value), None)


def _universal_input(n: int, kind: str | None = None) -> Callable[[SystemairDevice], bool]:
    """Universal input n is set up (as analog/digital when kind is given)."""
    def in_use(device: SystemairDevice) -> bool:
        title = _option_title(device, f"REG_UI_CFG_TYPE_{n}")
        if kind is None:
            return title not in (None, "VIEWS_SERVICE_INPUT_NOT_SET")
        return title == f"VIEWS_SERVICE_INPUT_{kind}_SELECTION"
    return in_use


def _manual_output(output: str) -> Callable[[SystemairDevice], bool]:
    """The output is in manual mode (its manual value applies)."""
    def manual(device: SystemairDevice) -> bool:
        return device.option_title(f"REG_MANUAL_OVERRIDE_OUTPUT_{output}") == "USER_MODES_MANUAL_TITLE"
    return manual


def output_connected(config_register: str) -> Callable[[SystemairDevice], bool]:
    """The output has a function (its type is not Inactive)."""
    def in_use(device: SystemairDevice) -> bool:
        return _option_title(device, config_register) not in (None, "VIEWS_SERVICE_OUTPUT_AO_TYPES_INACTIVE")
    return in_use


ON_OFF_OPTIONS = {"_OFF", "_ON"}


def _digital_input(n: int) -> Callable[[SystemairDevice], bool]:
    def in_use(device: SystemairDevice) -> bool:
        return _option_title(device, f"REG_DI_CONNECTION_{n}") not in (None, "VIEWS_SERVICE_INPUT_DIGITAL_INACTIVE_TITLE")
    return in_use


@dataclass(frozen=True)
class ConfigRegister:
    register: str
    name: str | None = None
    enabled_default: bool = False
    category: EntityCategory = EntityCategory.CONFIG
    icon: str | None = None
    # Overrides the unit from the metadata (some registers have none).
    unit: str | None = None
    # Enabled by default when this holds at setup, e.g. the settings of an input that is in use.
    in_use: Callable[[SystemairDevice], bool] | None = None
    # The entity is available only while this holds, e.g. a manual value while the output is in manual mode.
    active: Callable[[SystemairDevice], bool] | None = None
    # Written although the unit flags it read-only, as the SaveConnect app does (analog manual values).
    writable: bool = False

    def enabled_by_default(self, device: SystemairDevice) -> bool:
        return self.enabled_default or (self.in_use is not None and self.in_use(device))

    @property
    def key(self) -> str:
        """Part of the unique id; equals the original select keys (e.g. reg_do_cfg_connection_1)."""
        return self.register.lower()

    @property
    def display_name(self) -> str:
        return self.name or self.register.removeprefix("REG_").replace("_", " ").capitalize()

    def platform(self, device: SystemairDevice) -> str | None:
        # Read the registry directly so setup does not add the register to the regular poll.
        reg = getattr(device.registry, self.register, None)
        if reg is None or (reg.readOnly and not self.writable):
            return None
        if reg.options:
            return "switch" if {o.title for o in reg.options} == ON_OFF_OPTIONS else "select"
        if isinstance(reg.value, bool) or str(reg.value).lower() in ("true", "false"):
            return "switch"
        if isinstance(reg.value, SaveConnectTime):
            return "time"
        if isinstance(reg.min, int) and isinstance(reg.max, int):
            return "number"
        return None


def _preset(mode: str, title: str, unit: str | None) -> list[ConfigRegister]:
    return [
        ConfigRegister(f"REG_USERMODE_{mode}_TIME", f"{title} duration", True, icon="mdi:timer-outline", unit=unit),
        ConfigRegister(f"REG_USERMODE_{mode}_AIRFLOW_LEVEL_SAF", f"{title} supply airflow", icon="mdi:fan"),
        ConfigRegister(f"REG_USERMODE_{mode}_AIRFLOW_LEVEL_EAF", f"{title} extract airflow", icon="mdi:fan"),
    ]


CONFIG_REGISTERS: tuple[ConfigRegister, ...] = (
    # Everyday settings
    ConfigRegister("REG_ECO_MODE_ON_OFF", "Eco mode", True, icon="mdi:leaf"),
    ConfigRegister("REG_FREE_COOLING_ON_OFF", "Free cooling", True, icon="mdi:snowflake"),
    *_preset("HOLIDAY", "Holiday", UnitOfTime.DAYS),
    *_preset("AWAY", "Away", UnitOfTime.HOURS),
    *_preset("FIREPLACE", "Fireplace", UnitOfTime.MINUTES),
    *_preset("REFRESH", "Refresh", UnitOfTime.MINUTES),
    *_preset("CROWDED", "Crowded", UnitOfTime.HOURS),
    ConfigRegister("REG_USERMODE_CROWDED_T_OFFSET", "Crowded temperature offset"),
    ConfigRegister("REG_USERMODE_COOKERHOOD_AIRFLOW_LEVEL_SAF", "Cooker hood supply airflow", icon="mdi:fan"),
    ConfigRegister("REG_USERMODE_COOKERHOOD_AIRFLOW_LEVEL_EAF", "Cooker hood extract airflow", icon="mdi:fan"),
    ConfigRegister("REG_USERMODE_VACUUMCLEANER_AIRFLOW_LEVEL_SAF", "Vacuum cleaner supply airflow", icon="mdi:fan"),
    ConfigRegister("REG_USERMODE_VACUUMCLEANER_AIRFLOW_LEVEL_EAF", "Vacuum cleaner extract airflow", icon="mdi:fan"),
    ConfigRegister("REG_FILTER_PERIOD", "Filter period", unit="mo", icon="mdi:air-filter"),
    ConfigRegister("REG_ECO_T_Y1_OFFSET", "Eco heater offset", unit=UnitOfTemperature.CELSIUS),
    ConfigRegister("REG_FREE_COOLING_MIN_SPEED_LEVEL_SAF", "Free cooling supply airflow", icon="mdi:fan"),
    ConfigRegister("REG_FREE_COOLING_MIN_SPEED_LEVEL_EAF", "Free cooling extract airflow", icon="mdi:fan"),
    ConfigRegister("REG_FREE_COOLING_ROOM_CANCEL_T", "Free cooling room cancel temperature"),
    ConfigRegister("REG_FREE_COOLING_OUTDOOR_NIGHTTIME_DEACTIVATION_HIGH_T_LIMIT", "Free cooling outdoor high limit"),
    ConfigRegister("REG_FREE_COOLING_OUTDOOR_NIGHTTIME_DEACTIVATION_LOW_T_LIMIT", "Free cooling outdoor low limit"),
    ConfigRegister("REG_FREE_COOLING_START_TIME_H", "Free cooling start time", True, icon="mdi:clock-start"),
    ConfigRegister("REG_FREE_COOLING_END_TIME_H", "Free cooling end time", True, icon="mdi:clock-end"),
    ConfigRegister("REG_DEFROSTING_MODE", "Defrosting mode", True, icon="mdi:snowflake-melt"),
    ConfigRegister("REG_HEAT_EXCHANGER_COOLING_RECOVERY_ON_OFF", "Cooling recovery", True, icon="mdi:snowflake"),
    ConfigRegister("REG_COOLER_RECOVERY_LIMIT_T", "Cooling recovery limit", True),
    ConfigRegister("REG_PASSIVE_HOUSE_ACTIVATION", "Passive house", icon="mdi:home-thermometer"),
    ConfigRegister("REG_FAN_MANUAL_STOP_ALLOWED", "Manual fan stop allowed", icon="mdi:fan-off"),
    ConfigRegister("REG_ALARM_LOW_SAT_ENABLED", "Low supply air temperature alarm", icon="mdi:thermometer-alert"),
    # Temperature registers are in this unit (the values change with it).
    ConfigRegister("REG_SYSTEM_UNIT_TEMPERATURE", "Temperature unit", icon="mdi:temperature-celsius"),
    ConfigRegister("REG_PDM_CORRECTION_T", "Built-in extract air temperature correction", icon="mdi:tune"),
    ConfigRegister("REG_PDM_CORRECTION_RH", "Built-in humidity correction", icon="mdi:tune"),
    # Outdoor compensation: airflow lowered in winter / raised in summer depending on the outdoor temperature.
    ConfigRegister("REG_FAN_OUTDOOR_COMP_TYPE", "Outdoor compensation type", icon="mdi:fan"),
    *(ConfigRegister(f"REG_FAN_OUTDOOR_COMP_{reg}_{season.upper()}", f"Outdoor compensation {season} {what}")
      for season in ("winter", "summer")
      for reg, what in (("START_T", "start temperature"), ("STOP_T", "stop temperature"), ("VALUE", "value"))),
    ConfigRegister("REG_ROTOR_RH_TRANSFER_CTRL_ON_OFF", "Moisture transfer", True, icon="mdi:water-sync"),
    ConfigRegister("REG_ROTOR_RH_TRANSFER_CTRL_SETPOINT", "Moisture transfer setpoint", True, icon="mdi:water-percent"),
    # Airflow range the unit uses for demand control (air quality: CO2 / humidity).
    ConfigRegister("REG_IAQ_SPEED_LEVEL_MIN", "Air quality minimum airflow", True, icon="mdi:fan-chevron-down"),
    ConfigRegister("REG_IAQ_SPEED_LEVEL_MAX", "Air quality maximum airflow", True, icon="mdi:fan-chevron-up"),
    ConfigRegister("REG_DEMC_CO2_SETTINGS_ON_OFF", "Demand control CO2"),
    ConfigRegister("REG_DEMC_CO2_SETTINGS_SP", "CO2 setpoint", True, icon="mdi:molecule-co2"),
    ConfigRegister("REG_DEMC_CO2_SETTINGS_PBAND", "CO2 P-band", icon="mdi:tune"),
    ConfigRegister("REG_DEMC_CO2_SETTINGS_ITIME", "CO2 integration time", icon="mdi:tune"),
    ConfigRegister("REG_DEMC_RH_SETTINGS_ON_OFF", "Demand control humidity"),
    ConfigRegister("REG_DEMC_RH_SETTINGS_SP_SUMMER", "Humidity setpoint summer", True, icon="mdi:water-percent"),
    ConfigRegister("REG_DEMC_RH_SETTINGS_SP_WINTER", "Humidity setpoint winter", True, icon="mdi:water-percent"),
    ConfigRegister("REG_DEMC_SUMMER_WINTER_T", "Humidity winter mode temperature", True, icon="mdi:snowflake-thermometer"),
    ConfigRegister("REG_DEMC_RH_SETTINGS_PBAND", "Humidity P-band", icon="mdi:tune"),
    ConfigRegister("REG_DEMC_RH_SETTINGS_ITIME", "Humidity integration time", icon="mdi:tune"),
    ConfigRegister("REG_TC_CONTROL_MODE", "Temperature control mode"),

    # Digital outputs; DO1 type was already enabled before
    ConfigRegister("REG_DO_CFG_CONNECTION_1", "Digital Output 1 Type", True, icon="mdi:connection"),
    ConfigRegister("REG_MANUAL_OVERRIDE_OUTPUT_DO1", "Digital Output 1 Value Type", True, icon="mdi:connection"),
    *(ConfigRegister(f"REG_DO_CFG_CONNECTION_{n}", f"Digital Output {n} Type", icon="mdi:connection") for n in range(2, 5)),
    *(ConfigRegister(f"REG_MANUAL_OVERRIDE_OUTPUT_DO{n}", f"Digital Output {n} Value Type", icon="mdi:connection")
      for n in range(2, 5)),
    # On/off of a digital output in manual mode; enabled by default for outputs that have a function.
    *(ConfigRegister(f"REG_MANUAL_OVERRIDE_OUTPUT_DO{n}_VALUE", f"Digital Output {n} Manual Value",
                     icon="mdi:electric-switch", in_use=output_connected(f"REG_DO_CFG_CONNECTION_{n}"), active=_manual_output(f"DO{n}"))
      for n in range(1, 5)),
    # Analog outputs
    *(ConfigRegister(f"REG_AO_CFG_CONNECTION_{n}", f"Analog Output {n} Type", icon="mdi:connection") for n in range(1, 6)),
    *(ConfigRegister(f"REG_MANUAL_OVERRIDE_OUTPUT_AO{n}", f"Analog Output {n} Value Type", icon="mdi:connection")
      for n in range(1, 6)),
    # Level of an analog output in manual mode, 0-10 V; enabled by default for outputs that have a function.
    *(ConfigRegister(f"REG_MANUAL_OVERRIDE_OUTPUT_AO{n}_VALUE", f"Analog Output {n} Manual Value", icon="mdi:sine-wave",
                     in_use=output_connected(f"REG_AO_CFG_CONNECTION_{n}"),
                     active=_manual_output(f"AO{n}"), writable=True)
      for n in range(1, 6)),
    # Fans and triac in manual override
    *(ConfigRegister(f"REG_MANUAL_OVERRIDE_OUTPUT_{out}", f"{title} Value Type") for out, title in
      (("SAF", "Supply Fan"), ("EAF", "Extract Fan"), ("TRIAC", "Triac"))),
    *(ConfigRegister(f"REG_MANUAL_OVERRIDE_OUTPUT_{out}_VALUE", f"{title} Manual Value", active=_manual_output(out))
      for out, title in
      (("SAF", "Supply Fan"), ("EAF", "Extract Fan"), ("TRIAC", "Triac"))),
    # Inputs. A universal input is analog or digital (type); the settings of that kind apply.
    # The settings of inputs in use are enabled by default.
    *(ConfigRegister(f"REG_UI_CFG_TYPE_{n}", f"Universal Input {n} Type", icon="mdi:import",
                     in_use=_universal_input(n)) for n in range(1, 7)),
    *(ConfigRegister(f"REG_UI_CONNECTION_ANALOG{n}", f"Universal Input {n} Analog Function", icon="mdi:import",
                     in_use=_universal_input(n, "ANALOG")) for n in range(1, 7)),
    *(ConfigRegister(f"REG_UI_CFG_CORRECTION_ANALOG{n}", f"Universal Input {n} Sensor Correction", icon="mdi:tune",
                     in_use=_universal_input(n, "ANALOG")) for n in range(1, 7)),
    *(ConfigRegister(f"REG_UI_CONNECTION_DIGITAL{n}", f"Universal Input {n} Digital Function", icon="mdi:import",
                     in_use=_universal_input(n, "DIGITAL")) for n in range(1, 7)),
    *(ConfigRegister(f"REG_UI_CFG_POLARITY_DIGITAL{n}", f"Universal Input {n} Polarity", icon="mdi:import",
                     in_use=_universal_input(n, "DIGITAL")) for n in range(1, 7)),
    *(ConfigRegister(f"REG_DI_CONNECTION_{n}", f"Digital Input {n} Function", icon="mdi:import",
                     in_use=_digital_input(n)) for n in range(1, 3)),
    *(ConfigRegister(f"REG_DI_CFG_POLARITY_{n}", f"Digital Input {n} Polarity", icon="mdi:import",
                     in_use=_digital_input(n)) for n in range(1, 3)),
    *(ConfigRegister(f"REG_AI_CFG_CONNECTION_NTC{n}", f"Temperature Input {n} Function", icon="mdi:thermometer")
      for n in range(1, 8)),
    *(ConfigRegister(f"REG_AI_CFG_CORRECTION_NTC{n}", f"Temperature Input {n} Correction", icon="mdi:tune")
      for n in range(1, 8)),
    # Unit components
    ConfigRegister("REG_HEAT_EXCHANGER_TYPE", "Heat Exchanger Type Setting"),
    ConfigRegister("REG_UNIT_CONFIG_REHEATER_TYPE", "Heater Setting"),
    ConfigRegister("REG_UNIT_CONFIG_COOLER", "Cooler Setting"),
    ConfigRegister("REG_UNIT_CONFIG_EXTRA_CONTROLLER", "Extra Controller Setting"),
    ConfigRegister("REG_UNIT_CONFIG_BYPASS_LOCATION", "Bypass Location"),
    ConfigRegister("REG_UNIT_CONFIG_SEC_AIR", "Secondary Air"),
    ConfigRegister("REG_UNIT_CONFIG_RHS_PDM", "Built-in Humidity Sensor"),
)


def registers_for(device: SystemairDevice, platform: str) -> list[ConfigRegister]:
    return [spec for spec in CONFIG_REGISTERS if spec.platform(device) == platform]
