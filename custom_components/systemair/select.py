"""Select entities for unit settings that have a list of options."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SystemairConfigEntry
from .config_entity import SystemairConfigEntity
from .config_registers import registers_for
from .device import option_keys


async def async_setup_entry(
    hass: HomeAssistant, entry: SystemairConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        SystemairSelect(device, spec)
        for device in entry.runtime_data.devices
        for spec in registers_for(device, "select")
    )


class SystemairSelect(SystemairConfigEntity, SelectEntity):
    """Options are stable keys from the SaveConnect option titles; labels come from the translations."""

    _description_class = SelectEntityDescription

    def _option_map(self) -> dict[str, int]:
        return option_keys(self._reg.options if self._reg else None)

    @property
    def options(self) -> list[str]:
        return list(self._option_map())

    @property
    def current_option(self) -> str | None:
        return self._device.option_state(self._spec.register)

    async def async_select_option(self, option: str) -> None:
        value = self._option_map().get(option)
        if value is None:
            raise ServiceValidationError(f"Unknown option {option}")
        await self._write(str(value))
