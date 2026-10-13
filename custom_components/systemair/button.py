"""Button that clears the unit's alarms."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SystemairConfigEntry
from .alarms import ALARM_ACTIVE, ALARMS
from .device import SystemairDevice
from .entity import SystemairEntity

_LOGGER = logging.getLogger(__name__)


def clear_register(alarm_register: str) -> str:
    """REG_ALARM_X_ALARM -> REG_ALARM_X_CLEAR_ALARM."""
    return alarm_register.removesuffix("_ALARM") + "_CLEAR_ALARM"


def alarms_to_clear(device: SystemairDevice) -> list[str]:
    """Clear registers of the active alarms (those SaveConnect lists; waiting/acknowledged ones are left alone)."""
    return [
        clear_register(register)
        for register in ALARMS
        if device.int_value(register) == ALARM_ACTIVE and device.register(clear_register(register)) is not None
    ]


CLEAR_ALARMS = ButtonEntityDescription(
    key="clear_alarms", name="Clear alarms", icon="mdi:alarm-light-off", entity_category=EntityCategory.CONFIG
)


async def async_setup_entry(
    hass: HomeAssistant, entry: SystemairConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(SystemairClearAlarmsButton(device) for device in entry.runtime_data.devices)


class SystemairClearAlarmsButton(SystemairEntity, ButtonEntity):
    """Writes the clear register of every alarm that is set, as the unit's panel does."""

    entity_description = CLEAR_ALARMS

    def __init__(self, device: SystemairDevice) -> None:
        super().__init__(device, CLEAR_ALARMS.key)

    async def async_press(self) -> None:
        registers = alarms_to_clear(self._device)
        if not registers:
            _LOGGER.info("%s: no active alarms to clear", self._device.name)
            return
        _LOGGER.info("%s: clearing %s", self._device.name,
                     ", ".join(ALARMS[clear.replace("_CLEAR_ALARM", "_ALARM")] for clear in registers))
        for register in registers:
            await self._device.async_write_register(register, True)
