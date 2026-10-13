"""Client for the Systemair SAVE Connect cloud API (GraphQL over HTTP, plus a status websocket)."""
import asyncio
import json
import logging
import ssl
import time
import typing

import httpx

from .auth import SaveConnectAuth
from .const import IdCheck, UserPresets, WriteRegister, check_idregister, register_ids
from .data import SaveConnectData
from .exceptions import AuthenticationError
from .graphql import ALL_REGISTER_IDS, SaveConnectGraphQL, missing_data_item, unit_busy
from .models import SaveConnectDevice
from .registry import RegisterWrite
from .websocket import WSClient

_LOGGER = logging.getLogger(__name__)

PRESET_TIMER_REGISTERS = {
    UserPresets.CROWDED: "REG_USERMODE_CROWDED_TIME",
    UserPresets.HOLIDAY: "REG_USERMODE_HOLIDAY_TIME",
    UserPresets.FIREPLACE: "REG_USERMODE_FIREPLACE_TIME",
    UserPresets.AWAY: "REG_USERMODE_AWAY_TIME",
    UserPresets.REFRESH: "REG_USERMODE_REFRESH_TIME",
}


# Minimum seconds between two writes.
WRITE_INTERVAL = 1.0

# Unknown ids a read drops one by one before giving up (each costs a request).
MAX_MISSING_IDS = 5
# A request the unit answers with SERVER_BUSY is sent once more after this many seconds.
BUSY_RETRY_DELAY = 5


class SaveConnect:
    """The SaveConnect that consumes the SaveConnect API."""

    def __init__(self,
                 email,
                 password,
                 ws_enabled=True,
                 wss_url="wss://homesolutions.systemair.com/streaming/",
                 http_retries=3,
                 http_client: httpx.AsyncClient | None = None,
                 ssl_context: ssl.SSLContext | None = None,
                 ):
        """
        @param ws_enabled: open a websocket for status events
        @param http_retries: connection retries per HTTP request (only for clients created here)
        @param http_client: client to use instead of creating one; it keeps the SSO cookies,
            so it must not be shared with other services. Not closed by close().
        @param ssl_context: TLS context for the websocket; created in a thread when not given
        """
        self.email = email
        self.password = password
        self.ws_enabled = ws_enabled
        self._http_retries = http_retries

        self.data = SaveConnectData()
        self.graphql = SaveConnectGraphQL(self, http_client)
        self.auth = SaveConnectAuth(self, http_client)

        self._token_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._last_write = 0.0
        # Full-read ids per device when check_register_ids corrected the table.
        self._read_ids: typing.Dict[str, typing.List[int]] = {}
        # Per device: ids the unit listed at the register id check, and ids it no longer has.
        self._export_ids: typing.Dict[str, typing.List[int]] = {}
        self._missing_ids: typing.Dict[str, typing.Set[int]] = {}
        self._ws = WSClient(self, url=wss_url, callback=self.on_ws_data, ssl_context=ssl_context)

        """Called with the device id after a push event changed its data."""
        self.on_push: typing.Callable[[str], None] | None = None

    @property
    def http_retries(self):
        return self._http_retries

    @property
    def translations(self):
        return self.data.translations

    @property
    def ws_connected(self):
        return self._ws.is_connected()

    async def login(self):
        """Authenticate with email and password; starts the websocket when enabled."""
        async with self._token_lock:
            success = await self.auth.auth(self.email, self.password)
        if success and self.ws_enabled:
            self._ws.start()
        return success

    async def ensure_token(self, force_refresh=False) -> bool:
        """Make sure a valid access token is present: refresh it, or log in again if refreshing fails.

        Returns False when the login service cannot be reached. Raises
        AuthenticationError when the credentials are rejected.
        """
        async with self._token_lock:
            if not force_refresh and self.auth.is_auth():
                return True
            if await self.auth.refresh_token():
                return True
            _LOGGER.info("Token refresh failed, logging in again")
            try:
                logged_in = await self.auth.auth(self.email, self.password)
            except httpx.HTTPError as err:
                _LOGGER.warning("Systemair login failed: %r", err)
                return False
            if not logged_in:
                raise AuthenticationError("SaveConnect rejected the email or password")
            return True

    async def close(self):
        await self._ws.stop()
        await self.graphql.close()
        await self.auth.close()

    async def on_ws_data(self, data) -> bool:
        """Handle a message from the streaming API.

        For LEGACY units SaveConnect sends no register values here; it sends
        SYSTEM_EVENTs such as DEVICE_STATUS_UPDATE (a status summary, sent in
        answer to BroadcastDeviceStatuses) and connection events.
        """
        payload = json.loads(data)
        message_type = payload.get("type")
        action = payload.get("action")
        properties = payload.get("properties") or {}
        device_id = properties.get("id")
        _LOGGER.debug("Websocket %s/%s for %s", message_type, action, device_id)

        if message_type == "DEVICE_CONNECTED":
            self.data.set_availability(device_id, available=True)
        elif message_type == "DEVICE_DISCONNECTED":
            self.data.set_availability(device_id, available=False)
        elif message_type == "SYSTEM_EVENT" and action == "DEVICE_STATUS_UPDATE":
            if not self.data.update_status(device_id, properties):
                return False
        elif message_type == "DEVICE_PUSH_EVENT":
            if not self.data.apply_items(device_id, payload.get("dataItems")):
                return False
        else:
            return False

        if self.on_push:
            self.on_push(device_id)
        return True

    async def read_data(self, device: SaveConnectDevice) -> bool:
        """Read all registers of a device.

        If the read fails because the unit no longer has one of the ids, that
        id is left out and the read retried (see _read_ids_skipping_missing).
        When too many ids are gone, only the ids the unit reported at the
        register id check and those read before are tried.
        """
        device_id = device.identifier
        ids = self._read_ids.get(device_id) or ALL_REGISTER_IDS
        if await self._read_ids_skipping_missing(device, ids):
            return True
        if missing_data_item(self.graphql.last_error) is None:
            return False  # cloud or unit unavailable, not a stale id table
        fallback = set(self._export_ids.get(device_id, ())) | {reg.register_ for _, reg in device.registry if reg}
        fallback -= self._missing_ids.get(device_id, set())
        if not fallback or fallback >= set(ids) - self._missing_ids.get(device_id, set()):
            return False
        _LOGGER.warning("Full read of %s failed; reading only the %d ids known to work", device.name, len(fallback))
        return await self._read_ids_skipping_missing(device, sorted(fallback))

    async def _read_ids_skipping_missing(self, device: SaveConnectDevice, ids) -> bool:
        """GetDataItems for ids; ids the unit reports as unknown are dropped (for good) and the read retried.

        One unknown id fails the whole request, and the error names only that
        id, so each one costs a request; after MAX_MISSING_IDS the read gives up.
        A SERVER_BUSY answer is retried once after BUSY_RETRY_DELAY. Other failures (cloud or unit unreachable) return False at once.
        """
        device_id = device.identifier
        missing = self._missing_ids.setdefault(device_id, set())
        retried_busy = False
        for _ in range(MAX_MISSING_IDS + 2):
            request = [i for i in ids if i not in missing]
            if not request:
                return False
            if await self.graphql.read_data_items(device_id, request):
                return True
            if unit_busy(self.graphql.last_error) and not retried_busy:
                _LOGGER.info("%s is busy; reading again in %d s", device.name, BUSY_RETRY_DELAY)
                retried_busy = True
                await asyncio.sleep(BUSY_RETRY_DELAY)
                continue
            unknown = missing_data_item(self.graphql.last_error)
            if unknown is None or unknown not in request:
                return False
            _LOGGER.warning("%s has no data item %s any more; leaving it out of reads. "
                            "Please report this so the register id table can be updated.", device.name, unknown)
            missing.add(unknown)
        return False

    def missing_ids(self, device_id: str) -> typing.Set[int]:
        """Ids reads left out because the unit no longer has them."""
        return set(self._missing_ids.get(device_id, ()))

    async def check_register_ids(self, device: SaveConnectDevice) -> typing.Optional[IdCheck]:
        """Compare the static id table with the ids the unit reports; one request of about 300 KB.

        Registers whose id changed or that the table lacks are read with the
        unit's id from then on. Returns None when the export is unavailable.
        """
        items = await self.graphql.export_data_items(device.identifier)
        if not items:
            return None
        self._export_ids[device.identifier] = [item["id"] for item in items if item.get("id") is not None]
        check = check_idregister(items)
        if not check.ok:
            self._read_ids[device.identifier] = register_ids(check)
        return check

    async def read_registers(self, device: SaveConnectDevice, names) -> bool:
        """Read only the named registers (they must have been read once, so their ids are known)."""
        ids = sorted({reg.register_ for name in names if (reg := getattr(device.registry, name, None)) is not None})
        if not ids:
            return True
        return await self._read_ids_skipping_missing(device, ids)

    async def write_data(self, device: SaveConnectDevice, register: RegisterWrite, is_import=False):
        """Write a raw register id/value pair; returns True on success.

        Writes go out one at a time, at least WRITE_INTERVAL seconds apart, so
        quick changes do not reach the unit as a burst.
        """
        async with self._write_lock:
            wait = self._last_write + WRITE_INTERVAL - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                for attempt in range(2):
                    if await self.graphql.write_data_items(
                        device_id=device.identifier, register_pair=register, is_import=is_import
                    ):
                        return True
                    if attempt or not unit_busy(self.graphql.last_error):
                        return False
                    _LOGGER.info("%s is busy; writing again in %d s", device.name, BUSY_RETRY_DELAY)
                    await asyncio.sleep(BUSY_RETRY_DELAY)
            finally:
                self._last_write = time.monotonic()

    async def write_register(self, device: SaveConnectDevice, name: str, value, allow_read_only=False):
        """
        Write a register by registry name (e.g. "REG_TC_SP").
        The value is checked against the register's options / min / max, and
        the local registry is updated when the write succeeds. allow_read_only
        writes a register the unit flags read-only but accepts writes to in some
        modes (an analog output's manual value).
        """
        item = self.data.effective_item(device, name)
        if item is None:
            raise ValueError(f"Register {name} has not been read from {device.identifier}")
        if item.readOnly and not allow_read_only:
            raise ValueError(f"Register {name} is read-only")

        if item.options and int(value) not in {o.value for o in item.options}:
            raise ValueError(f"{value} is not a valid option for {name}")
        if isinstance(item.min, int) and isinstance(item.max, int) and not isinstance(value, bool):
            if not item.min <= int(value) <= item.max:
                raise ValueError(f"{value} is outside {item.min}..{item.max} for {name}")

        success = await self.write_data(device, RegisterWrite(register=item.register_, value=value))
        if success:
            self.data.apply_items(device.identifier, [{"id": item.register_, "value": value}])
        return success

    async def set_preset(self, device: SaveConnectDevice, mode: str, duration=None):
        """
        Set the user mode (preset), a UserPresets value.
        @param duration: optional run time for timed presets, in the unit's own unit for that timer
        """
        _LOGGER.debug("set_preset %s / %s", mode, duration)
        if duration is not None and mode in PRESET_TIMER_REGISTERS:
            await self.write_register(device, PRESET_TIMER_REGISTERS[mode], str(duration))

        # REG_USERMODE_HMI_CHANGE_REQUEST counts from 1 (1 = Auto) while the
        # mode register REG_USERMODE_MODE_HMI counts from 0 (0 = Auto).
        # The change request register is write-only, so it has no registry entry.
        return await self.write_data(
            device=device,
            register=RegisterWrite(register=WriteRegister.REG_USERMODE_HMI_CHANGE_REQUEST, value=str(int(mode) + 1))
        )

    async def get_devices(self, update=True, fetch_device_info=True) -> typing.List[SaveConnectDevice]:
        """List the account's devices, optionally re-fetching them and reading all their registers."""
        if update:
            devices = await self.graphql.get_account(with_translations=not self.data.translations)
        else:
            devices = list(self.data.devices.values())

        if fetch_device_info:
            for device in devices:
                await self.read_data(device)
        return devices
