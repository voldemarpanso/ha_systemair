"""Time entities for hour:minute unit settings (free cooling start and end)."""
from __future__ import annotations

import json
from datetime import time

from homeassistant.components.time import TimeEntity, TimeEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SystemairConfigEntry
from .config_entity import SystemairConfigEntity
from .config_registers import registers_for
from .saveconnect.models import SaveConnectTime


async def async_setup_entry(
    hass: HomeAssistant, entry: SystemairConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        SystemairTime(device, spec)
        for device in entry.runtime_data.devices
        for spec in registers_for(device, "time")
    )


def _minutes(value: SaveConnectTime | time) -> int:
    return value.hour * 60 + value.minute


def in_window(value: time, start: SaveConnectTime | None, end: SaveConnectTime | None) -> bool:
    """Whether value lies in the register's min..max, which may wrap past midnight (e.g. 21:00..08:00)."""
    if not isinstance(start, SaveConnectTime) or not isinstance(end, SaveConnectTime):
        return True
    low, high, minutes = _minutes(start), _minutes(end), _minutes(value)
    return low <= minutes <= high if low <= high else minutes >= low or minutes <= high


class SystemairTime(SystemairConfigEntity, TimeEntity):

    _description_class = TimeEntityDescription

    @property
    def native_value(self) -> time | None:
        reg = self._reg
        value = reg.value if reg else None
        if not isinstance(value, SaveConnectTime):
            return None
        return time(value.hour % 24, value.minute)

    async def async_set_value(self, value: time) -> None:
        reg = self._reg
        if reg is not None and not in_window(value, reg.min, reg.max):
            raise ServiceValidationError(
                f"{value:%H:%M} is outside {reg.min.hour:02d}:{reg.min.minute:02d}-{reg.max.hour:02d}:{reg.max.minute:02d}"
            )
        # The SaveConnect app writes hour:minute values as JSON.
        await self._write(json.dumps({"hour": value.hour, "minute": value.minute}))
