"""The Systemair SAVE Connect integration."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

import httpx
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.httpx_client import create_async_httpx_client
from homeassistant.util.ssl import get_default_context

from .const import CONF_SCAN_INTERVAL, DOMAIN, HA_SC_CLOUD_PUSH, HA_SC_CLOUD_PUSH_DEFAULT, SCAN_INTERVAL
from .coordinator import SystemairCoordinator
from .device import SystemairDevice
from .repairs import update_register_id_issue
from .saveconnect import AuthenticationError, SaveConnect

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
    Platform.UPDATE,
]


@dataclass
class SystemairData:
    api: SaveConnect
    devices: list[SystemairDevice]


type SystemairConfigEntry = ConfigEntry[SystemairData]


async def async_setup_entry(hass: HomeAssistant, entry: SystemairConfigEntry) -> bool:
    """Log in to SaveConnect and set up one coordinator per device."""
    api = SaveConnect(
        email=entry.data[CONF_EMAIL],
        password=entry.data[CONF_PASSWORD],
        ws_enabled=entry.options.get(HA_SC_CLOUD_PUSH, entry.data.get(HA_SC_CLOUD_PUSH, HA_SC_CLOUD_PUSH_DEFAULT)),
        # Own client, not the shared one: it holds the SSO login cookies. HA closes it on stop.
        http_client=create_async_httpx_client(hass),
        ssl_context=get_default_context(),
    )

    # Runs on unload and also when setup fails after this point.
    entry.async_on_unload(api.close)
    try:
        logged_in = await api.login()
        sc_devices = await api.get_devices(update=True, fetch_device_info=False) if logged_in else []
    except httpx.HTTPError as err:
        raise ConfigEntryNotReady(f"Cannot reach SaveConnect: {err}") from err
    if not logged_in:
        raise ConfigEntryAuthFailed("SaveConnect login failed")

    scan_interval = timedelta(seconds=entry.options.get(CONF_SCAN_INTERVAL, SCAN_INTERVAL.total_seconds()))
    coordinators: dict[str, SystemairCoordinator] = {}
    devices = []
    for sc_device in sc_devices:
        device = SystemairDevice(api, sc_device)
        await _async_check_register_ids(hass, device)
        coordinator = SystemairCoordinator(hass, entry, device, scan_interval)
        await coordinator.async_config_entry_first_refresh()
        coordinators[device.device_id] = coordinator
        devices.append(device)

    @callback
    def on_push(device_id: str) -> None:
        if coordinator := coordinators.get(device_id):
            coordinator.async_set_updated_data(None)

    api.on_push = on_push

    entry.runtime_data = SystemairData(api=api, devices=devices)
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_options_change))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_check_register_ids(hass: HomeAssistant, device: SystemairDevice) -> None:
    """Check the static register id table against the unit once per setup."""
    try:
        device.id_check = await device.api.check_register_ids(device.device)
    except AuthenticationError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except httpx.HTTPError as err:
        _LOGGER.debug("Register id check for %s failed: %s", device.name, err)
        return
    update_register_id_issue(hass, device)
    check = device.id_check
    if check is None:
        _LOGGER.debug("Register id check for %s: export not available", device.name)
    elif check.ok:
        _LOGGER.debug("Register id check for %s: %d ids match", device.name, check.checked)
    else:
        _LOGGER.warning(
            "SystemAir register ids differ from the integration's table for %s (%d changed, %d missing); "
            "using the ids the unit reports. Please report this so the table can be updated: changed %s, missing %s",
            device.name, len(check.changed), len(check.missing), check.changed, check.missing,
        )


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: SystemairConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow removing a device that is no longer in the SaveConnect account."""
    current = {device.device_id for device in entry.runtime_data.devices}
    return not any(identifier in current for domain, identifier in device_entry.identifiers if domain == DOMAIN)


async def async_unload_entry(hass: HomeAssistant, entry: SystemairConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_on_options_change(hass: HomeAssistant, entry: SystemairConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
