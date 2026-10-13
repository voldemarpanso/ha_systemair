"""Diagnostics download: entry settings, device status and all register values."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from . import SystemairConfigEntry

TO_REDACT = {CONF_EMAIL, CONF_PASSWORD, "identifier", "name", "street", "zipcode", "city", "country",
             "REG_SYSTEM_SERIAL_NUMBER1"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: SystemairConfigEntry) -> dict[str, Any]:
    data = entry.runtime_data
    devices = []
    for device in data.devices:
        registers = {
            name: {"id": reg.register_, "modbus": reg.extension.modbusRegister, "value": reg.value}
            for name, reg in device.registry
            if reg is not None
        }
        devices.append({
            "device": async_redact_data(device.device.model_dump(exclude={"registry", "cb"}), TO_REDACT),
            "last_update_success": device.coordinator.last_update_success if device.coordinator else None,
            "polled_registers": sorted(device.used_registers),
            "register_id_check": device.id_check._asdict() if device.id_check else None,
            "registers": async_redact_data(registers, TO_REDACT),
        })
    return {
        "entry": {"data": async_redact_data(dict(entry.data), TO_REDACT), "options": dict(entry.options)},
        "websocket_connected": data.api.ws_connected,
        "devices": devices,
    }
