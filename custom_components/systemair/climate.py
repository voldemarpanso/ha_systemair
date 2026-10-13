"""Climate entity for the Systemair ventilation unit."""
from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityDescription,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SystemairConfigEntry
from .const import AIRFLOW_LEVELS, PRESETS
from .device import SystemairDevice
from .entity import SystemairEntity

MANUAL = "Manual"
MANUAL_AIRFLOW = "REG_USERMODE_MANUAL_AIRFLOW_LEVEL_SAF"


# Key "fan" is part of the unique id.
VENTILATION = ClimateEntityDescription(key="fan", name="Ventilation", icon="mdi:fan")


async def async_setup_entry(
    hass: HomeAssistant, entry: SystemairConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(SystemairClimate(device) for device in entry.runtime_data.devices)


class SystemairClimate(SystemairEntity, ClimateEntity):
    """Ventilation unit: setpoint, preset (user mode) and, in Manual, fan level."""

    entity_description = VENTILATION
    _attr_target_temperature_step = 0.5
    _attr_preset_modes = list(PRESETS)

    def __init__(self, device: SystemairDevice) -> None:
        super().__init__(device, VENTILATION.key)

    @property
    def supported_features(self) -> ClimateEntityFeature:
        # The fan level can only be chosen in Manual; Auto runs on demand and
        # timed presets have their own fixed level, so the control is hidden.
        features = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
        if self.preset_mode == MANUAL:
            features |= ClimateEntityFeature.FAN_MODE
        return features

    @property
    def preset_mode(self) -> str | None:
        return self._device.preset

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode != self.preset_mode:
            await self._device.async_set_preset(preset_mode)

    @property
    def fan_modes(self) -> list[str]:
        reg = self._device.register(MANUAL_AIRFLOW)
        values = [o.value for o in reg.options] if reg and reg.options else [2, 3, 4]
        return [AIRFLOW_LEVELS[v] for v in values]

    @property
    def fan_mode(self) -> str | None:
        level = self._device.int_value(MANUAL_AIRFLOW)
        return AIRFLOW_LEVELS[level] if level is not None and level < len(AIRFLOW_LEVELS) else None

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        if self.preset_mode != MANUAL:
            raise ServiceValidationError("The fan level can only be set in the Manual preset")
        if fan_mode not in self.fan_modes:
            raise ServiceValidationError(f"Unknown fan level {fan_mode}")
        await self._device.async_set_manual_airflow(AIRFLOW_LEVELS.index(fan_mode))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        level = self._device.airflow_level
        return {
            "airflow_level": AIRFLOW_LEVELS[level] if level is not None and level < len(AIRFLOW_LEVELS) else None,
            "active_functions": self._device.active_functions(),
        }

    @property
    def target_temperature(self) -> float | None:
        value = self._device.int_value("REG_TC_SP")
        return None if value is None else value / 10

    @property
    def temperature_unit(self) -> str:
        return self._device.temperature_unit

    @property
    def min_temp(self) -> float:
        reg = self._device.properties("REG_TC_SP")  # range depends on the temperature unit
        return reg.min / 10 if reg and isinstance(reg.min, int) else 12

    @property
    def max_temp(self) -> float:
        reg = self._device.properties("REG_TC_SP")
        return reg.max / 10 if reg and isinstance(reg.max, int) else 30

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        await self._device.async_set_temperature(temperature)

    @property
    def current_temperature(self) -> float | None:
        value = self._device.int_value("REG_SENSOR_EFT")
        return None if value is None else value / 10

    @property
    def current_humidity(self) -> int | None:
        return self._device.int_value("REG_SENSOR_RHS_PDM")

    @property
    def hvac_mode(self) -> HVACMode:
        """The unit decides itself between heating, heat recovery and cooling; Off when the fans are stopped.

        It cannot be set from here.
        """
        return HVACMode.OFF if self._device.airflow_level == 0 else HVACMode.AUTO

    @property
    def hvac_modes(self) -> list[HVACMode]:
        return [self.hvac_mode]

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode != self.hvac_mode:
            raise ServiceValidationError("The HVAC mode follows the unit and cannot be set")

    @property
    def hvac_action(self) -> HVACAction | None:
        """What the unit is doing; heat recovery alone counts as ventilating (see active_functions)."""
        device = self._device
        if device.airflow_level == 0:
            return HVACAction.OFF
        if device.bool_value("REG_FUNCTION_ACTIVE_DEFROSTING"):
            return HVACAction.DEFROSTING
        cooling_output = device.cooling_output()
        if (
            device.bool_value("REG_FUNCTION_ACTIVE_COOLING")
            or device.bool_value("REG_FUNCTION_ACTIVE_FREE_COOLING")
            or (cooling_output and device.bool_value(cooling_output))
        ):
            return HVACAction.COOLING
        if device.bool_value("REG_FUNCTION_ACTIVE_HEATING"):
            return HVACAction.HEATING
        return HVACAction.FAN
