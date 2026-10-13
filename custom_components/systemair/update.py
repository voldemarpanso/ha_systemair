"""Firmware version entities.

The IAM keeps firmware images for the main board and the control panel;
their versions (REG_PU_FLASH_VERSION_*) are shown as the latest version.
On a unit that is up to date they equal the running versions. SaveConnect
exposes no available version for the IAM itself, and no documented way to
start an update, so these entities only report.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.update import UpdateEntity, UpdateEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SystemairConfigEntry
from .device import SystemairDevice
from .entity import SystemairEntity


@dataclass(frozen=True, kw_only=True)
class SystemairUpdateEntityDescription(UpdateEntityDescription):
    installed_fn: Callable[[SystemairDevice], str | None]
    latest_fn: Callable[[SystemairDevice], str | None]


UPDATES: tuple[SystemairUpdateEntityDescription, ...] = (
    SystemairUpdateEntityDescription(
        key="firmware_main_board",
        name="Main board firmware",
        installed_fn=lambda device: device.main_board_version,
        latest_fn=lambda device: device.main_board_flash_version,
    ),
    SystemairUpdateEntityDescription(
        key="firmware_control_panel",
        name="Control panel firmware",
        installed_fn=lambda device: device.hmi_version,
        latest_fn=lambda device: device.hmi_flash_version,
    ),
    SystemairUpdateEntityDescription(
        key="firmware_iam",
        name="IAM firmware",
        installed_fn=lambda device: device.iam_version,
        latest_fn=lambda device: device.iam_version,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: SystemairConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        SystemairUpdate(device, description)
        for device in entry.runtime_data.devices
        for description in UPDATES
        if description.installed_fn(device) is not None
    )


class SystemairUpdate(SystemairEntity, UpdateEntity):
    entity_description: SystemairUpdateEntityDescription
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, device: SystemairDevice, description: SystemairUpdateEntityDescription) -> None:
        super().__init__(device, description.key)
        self.entity_description = description

    @property
    def installed_version(self) -> str | None:
        return self.entity_description.installed_fn(self._device)

    @property
    def latest_version(self) -> str | None:
        return self.entity_description.latest_fn(self._device) or self.installed_version

    @property
    def in_progress(self) -> bool:
        return self._device.update_in_progress
