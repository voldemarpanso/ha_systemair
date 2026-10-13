"""Binary sensors for Systemair: alarms and digital outputs."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SystemairConfigEntry
from .alarms import ALARM_ACTIVE, ALARMS
from .device import SystemairDevice
from .entity import SystemairEntity


@dataclass(frozen=True, kw_only=True)
class SystemairBinarySensorEntityDescription(BinarySensorEntityDescription):
    is_on_fn: Callable[[SystemairDevice], bool | None]
    attributes_fn: Callable[[SystemairDevice], dict[str, Any]] | None = None


def alarm_state(device: SystemairDevice, register: str) -> str | None:
    title = device.option_title(register)
    return None if title is None else title.strip("_").lower()


def active_alarms(device: SystemairDevice) -> list[str]:
    return [name for register, name in ALARMS.items() if device.int_value(register) == ALARM_ACTIVE]


def alarm_description(register: str, name: str) -> SystemairBinarySensorEntityDescription:
    return SystemairBinarySensorEntityDescription(
        key=register.lower(),
        name=f"Alarm {name}",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        is_on_fn=lambda device: device.int_value(register) == ALARM_ACTIVE,
        attributes_fn=lambda device: {"state": alarm_state(device, register)},
    )


def output_description(n: int) -> SystemairBinarySensorEntityDescription:
    register = f"REG_OUTPUT_DO{n}"
    return SystemairBinarySensorEntityDescription(
        key=register.lower(),
        name=f"Digital Output {n}",
        icon="mdi:electric-switch",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda device: None if device.int_value(register) is None else device.int_value(register) > 0,
        attributes_fn=lambda device: {
            "function": device.translate(t) if (t := device.option_title(f"REG_DO_CFG_CONNECTION_{n}")) else None
        },
    )


BINARY_SENSORS: tuple[SystemairBinarySensorEntityDescription, ...] = (
    SystemairBinarySensorEntityDescription(
        key="problem",
        name="Problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=lambda device: bool(active_alarms(device)),
        attributes_fn=lambda device: {"active_alarms": active_alarms(device)},
    ),
    *(alarm_description(register, name) for register, name in ALARMS.items()),
    *(output_description(n) for n in range(1, 5)),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: SystemairConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        SystemairBinarySensor(device, description)
        for device in entry.runtime_data.devices
        for description in BINARY_SENSORS
        if description.key == "problem" or device.register(description.key.upper()) is not None
    )


class SystemairBinarySensor(SystemairEntity, BinarySensorEntity):
    entity_description: SystemairBinarySensorEntityDescription

    def __init__(self, device: SystemairDevice, description: SystemairBinarySensorEntityDescription) -> None:
        super().__init__(device, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.is_on_fn(self._device)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self._device)
