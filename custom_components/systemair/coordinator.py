"""Data update coordinator for a Systemair device."""
from __future__ import annotations

import logging
import time
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .alarms import LOG_REGISTERS, alarm_states
from .const import ACCOUNT_REFRESH_INTERVAL, DOMAIN, FULL_READ_INTERVAL, SCAN_INTERVAL
from .device import SystemairDevice
from .repairs import update_register_id_issue
from .saveconnect import AuthenticationError

_LOGGER = logging.getLogger(__name__)

# Delay before re-reading after a write, so the unit has applied the change.
REFRESH_AFTER_WRITE = 5


class SystemairCoordinator(DataUpdateCoordinator[None]):
    """Polls one device.

    The data lives in the device registry, so the coordinator carries no data
    of its own and is only used to schedule reads and notify entities. A
    regular poll reads only the registers entities have used; every
    FULL_READ_INTERVAL (and at start) all registers are read. The alarm log is
    read with those, and also when an alarm changes state.
    """

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, device: SystemairDevice, scan_interval: timedelta = SCAN_INTERVAL
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}-{device.device_id}",
            update_interval=scan_interval,
        )
        self.device = device
        device.coordinator = self
        self._last_account_refresh = time.monotonic()
        self._last_full_read: float | None = None
        self._cancel_refresh_after_write = None
        self._alarm_states: tuple | None = None

    async def _async_update_data(self) -> None:
        gone = len(self.device.api.missing_ids(self.device.device_id))
        try:
            await self._async_read()
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        finally:
            if len(self.device.api.missing_ids(self.device.device_id)) != gone:
                update_register_id_issue(self.hass, self.device)

    async def _async_read(self) -> None:
        api = self.device.api
        now = time.monotonic()
        if now - self._last_account_refresh > ACCOUNT_REFRESH_INTERVAL.total_seconds():
            account_devices = await api.get_devices(update=True, fetch_device_info=False)
            self._last_account_refresh = now
            self._reload_if_devices_changed({d.identifier for d in account_devices})

        full = (
            self._last_full_read is None
            or not self.device.used_registers
            or now - self._last_full_read > FULL_READ_INTERVAL.total_seconds()
        )
        if full:
            ok = await api.read_data(self.device.device)
        else:
            ok = await api.read_registers(self.device.device, self.device.used_registers)
        if not ok:
            raise UpdateFailed(f"Reading {self.device.name} failed")
        if full:
            self._last_full_read = now
        await self._async_read_alarm_log_on_change(full)

    async def _async_read_alarm_log_on_change(self, full: bool) -> None:
        states = alarm_states(self.device.registry)
        changed = self._alarm_states is not None and states != self._alarm_states
        self._alarm_states = states
        if changed and not full and not await self.device.api.read_registers(self.device.device, LOG_REGISTERS):
            _LOGGER.debug("Reading the alarm log of %s failed; it is read again with the next full read", self.device.name)

    @callback
    def _reload_if_devices_changed(self, account_ids: set[str]) -> None:
        """Set the entry up again when units were added to or removed from the account."""
        if not account_ids:
            return  # account request failed; nothing to compare
        known = {device.device_id for device in self.config_entry.runtime_data.devices}
        if account_ids != known:
            _LOGGER.info("SaveConnect account devices changed (%s -> %s); reloading", sorted(known), sorted(account_ids))
            self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)

    @callback
    def after_write(self) -> None:
        """Show the optimistic state now and confirm it with a read shortly after."""
        self.async_update_listeners()
        if self._cancel_refresh_after_write:
            self._cancel_refresh_after_write()

        @callback
        def _refresh(_now) -> None:
            self._cancel_refresh_after_write = None
            self.hass.async_create_task(self.async_refresh())

        self._cancel_refresh_after_write = async_call_later(self.hass, REFRESH_AFTER_WRITE, _refresh)

    async def async_shutdown(self) -> None:
        if self._cancel_refresh_after_write:
            self._cancel_refresh_after_write()
        await super().async_shutdown()
