import asyncio
import logging
import ssl

from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus, WebSocketException

from .exceptions import AuthenticationError

_LOGGER = logging.getLogger(__name__)

MIN_RETRY_DELAY = 5
MAX_RETRY_DELAY = 300


class WSClient:
    """Keeps a websocket to the SaveConnect streaming API open and passes messages to a callback."""

    def __init__(self, saveconnect, url, callback, on_connection_change=None, ssl_context: ssl.SSLContext | None = None):
        self.url = url
        # Loading the CA certificates blocks, so a missing context is created in a thread on first connect.
        self._ssl_context = ssl_context
        self.saveconnect = saveconnect
        self.callback = callback
        self.on_connection_change = on_connection_change
        self._connected = False
        self._task: asyncio.Task | None = None

    def is_connected(self):
        return self._connected

    def start(self):
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._run(), name="systemair-websocket")

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._set_connected(False)

    def _set_connected(self, connected):
        if connected != self._connected:
            self._connected = connected
            _LOGGER.debug("Websocket %s", "connected" if connected else "disconnected")
            if self.on_connection_change:
                self.on_connection_change(connected)

    async def _run(self):
        delay = MIN_RETRY_DELAY
        while True:
            try:
                await self.saveconnect.ensure_token()
                if self._ssl_context is None:
                    self._ssl_context = await asyncio.to_thread(ssl.create_default_context)
                async with connect(
                    self.url,
                    ssl=self._ssl_context,
                    subprotocols=["accessToken", self.saveconnect.auth.access_token],
                    ping_interval=30,
                    ping_timeout=20,
                ) as ws:
                    self._set_connected(True)
                    delay = MIN_RETRY_DELAY
                    async for message in ws:
                        try:
                            await self.callback(message)
                        except Exception:
                            _LOGGER.exception("Error handling websocket message: %s", message)
            except asyncio.CancelledError:
                raise
            except InvalidStatus as e:
                _LOGGER.warning("Websocket rejected: HTTP %s", e.response.status_code)
                if e.response.status_code == 401:
                    await self.saveconnect.ensure_token(force_refresh=True)
            except AuthenticationError:
                _LOGGER.warning("Websocket paused: SaveConnect rejected the login")
                delay = MAX_RETRY_DELAY
            except (OSError, asyncio.TimeoutError, WebSocketException) as e:
                _LOGGER.debug("Websocket connection lost: %r", e)
            finally:
                self._set_connected(False)

            _LOGGER.debug("Websocket reconnecting in %ss", delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, MAX_RETRY_DELAY)
