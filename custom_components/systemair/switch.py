"""Switch entities for on/off unit settings."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SystemairConfigEntry
from .config_entity import SystemairConfigEntity
from .config_registers import registers_for


async def async_setup_entry(
    hass: HomeAssistant, entry: SystemairConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        SystemairSwitch(device, spec)
        for device in entry.runtime_data.devices
        for spec in registers_for(device, "switch")
    )


class SystemairSwitch(SystemairConfigEntity, SwitchEntity):

    _description_class = SwitchEntityDescription

    @property
    def _on_off_options(self) -> bool:
        """Off/on register with options 0/1 instead of a boolean."""
        return bool(self._reg and self._reg.options)

    @property
    def is_on(self) -> bool | None:
        if self._on_off_options:
            value = self._device.int_value(self._spec.register)
            return None if value is None else value == 1
        return self._device.bool_value(self._spec.register)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._write("1" if self._on_off_options else True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._write("0" if self._on_off_options else False)
