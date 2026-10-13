"""Number entities for numeric unit settings."""
from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SystemairConfigEntry
from .config_entity import SystemairConfigEntity
from .config_registers import UNIT_CODES, registers_for


async def async_setup_entry(
    hass: HomeAssistant, entry: SystemairConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        SystemairNumber(device, spec)
        for device in entry.runtime_data.devices
        for spec in registers_for(device, "number")
    )


class SystemairNumber(SystemairConfigEntity, NumberEntity):
    """Raw register values are integers scaled by 10^decimals."""

    _attr_mode = NumberMode.BOX
    _description_class = NumberEntityDescription

    # Unit, range and decimals can depend on other settings (conditional properties), so they are read live.

    @property
    def _props(self):
        return self._device.properties(self._spec.register)

    @property
    def _scale(self) -> int:
        props = self._props
        return 10 ** ((props.decimals if props else None) or 0)

    @property
    def native_min_value(self) -> float:
        props = self._props
        return props.min / self._scale if props and isinstance(props.min, int) else super().native_min_value

    @property
    def native_max_value(self) -> float:
        props = self._props
        return props.max / self._scale if props and isinstance(props.max, int) else super().native_max_value

    @property
    def native_step(self) -> float:
        props = self._props
        return ((props.increment if props else None) or 1) / self._scale

    @property
    def native_unit_of_measurement(self) -> str | None:
        props = self._props
        return self._spec.unit or (UNIT_CODES.get(props.unit) if props else None)

    @property
    def device_class(self) -> NumberDeviceClass | None:
        if self.native_unit_of_measurement in (UnitOfTemperature.CELSIUS, UnitOfTemperature.FAHRENHEIT):
            return NumberDeviceClass.TEMPERATURE
        return None

    @property
    def native_value(self) -> float | None:
        value = self._device.int_value(self._spec.register)
        if value is None:
            return None
        scale = self._scale
        return value / scale if scale > 1 else value

    async def async_set_native_value(self, value: float) -> None:
        await self._write(str(int(round(value * self._scale))))
