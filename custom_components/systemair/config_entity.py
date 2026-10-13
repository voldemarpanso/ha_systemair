"""Base for entities generated from config_registers."""
from __future__ import annotations

from homeassistant.helpers.entity import EntityDescription

from .config_registers import ConfigRegister
from .device import SystemairDevice
from .entity import SystemairEntity


class SystemairConfigEntity(SystemairEntity):
    """The name comes from the translations (key = register name); display_name is the English fallback."""

    _description_class: type[EntityDescription]

    def __init__(self, device: SystemairDevice, spec: ConfigRegister) -> None:
        super().__init__(device, spec.key)
        self._spec = spec
        self.entity_description = self._description_class(
            key=spec.key,
            translation_key=spec.key,
            name=spec.display_name,
            entity_category=spec.category,
            entity_registry_enabled_default=spec.enabled_by_default(device),
            icon=spec.icon,
        )

    @property
    def _reg(self):
        return self._device.register(self._spec.register)

    async def _write(self, value) -> None:
        await self._device.async_write_register(self._spec.register, value, allow_read_only=self._spec.writable)

    @property
    def available(self) -> bool:
        return super().available and (self._spec.active is None or self._spec.active(self._device))
