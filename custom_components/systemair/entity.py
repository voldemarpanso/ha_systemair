"""Base entity for Systemair."""
from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import SAVECONNECT_NAME
from .coordinator import SystemairCoordinator
from .device import SystemairDevice


class SystemairEntity(CoordinatorEntity[SystemairCoordinator]):
    """Entity bound to one device and its coordinator."""

    _attr_has_entity_name = True

    def __init__(self, device: SystemairDevice, key: str) -> None:
        super().__init__(device.coordinator)
        self._device = device
        self._attr_unique_id = f"{SAVECONNECT_NAME}-{device.device_id}-{key}"
        # Names (and option labels) come from strings.json under this key; the
        # entity description's English name is the fallback.
        self._attr_translation_key = key

    @property
    def device_info(self):
        return self._device.device_info

    @property
    def available(self) -> bool:
        return super().available and self._device.online
