import json
import logging
import re
import typing
from json import JSONDecodeError

import httpx

from .const import register_ids
from .models import SaveConnectDevice
from .registry import RegisterWrite

_LOGGER = logging.getLogger(__name__)

API_URL = "https://homesolutions.systemair.com/gateway/api"
REMOTE_API_URL = "https://homesolutions.systemair.com/gateway/remote-api/"

ALL_REGISTER_IDS = register_ids()

DEVICE_FIELDS = """
    identifier
    name
    street
    zipcode
    city
    country
    deviceType { entry module scope type }
    status {
      connectionStatus
      startupWizardRequired
      updateInProgress
      filterLocked
      weekScheduleLocked
      serviceLocked
      hasAlarms
      units { temperature pressure flow }
    }
"""

QUERY_DEVICES = "query { GetAccountDevices { %s } }" % DEVICE_FIELDS
QUERY_DEVICES_AND_TRANSLATIONS = (
    "query { GetLoggedInUser { translations { key value } } GetAccountDevices { %s } }" % DEVICE_FIELDS
)
REQUEST_TIMEOUT = 60

QUERY_DATA_ITEMS = "query ($input: [Int]) { GetDataItems(input: $input) }"
# The unit's settings (holding registers) with ids and metadata; sensors are not included.
QUERY_EXPORT_DATA_ITEMS = "query { ExportDataItems { version type dataItems } }"
MUTATION_WRITE_DATA_ITEMS = "mutation ($input: WriteDataItemsInput!) { WriteDataItems(input: $input) }"


_MISSING_DATA_ITEM = re.compile(r"Could not find data item with id (\d+)")


def missing_data_item(error) -> typing.Optional[int]:
    """Id from the API error a read gets when it asks for an id the unit does not have."""
    match = _MISSING_DATA_ITEM.search(json.dumps(error)) if error else None
    return int(match.group(1)) if match else None


def unit_busy(error) -> bool:
    """The unit answered the relayed Modbus request with SERVER_BUSY (temporary)."""
    return bool(error) and '"SERVER_BUSY"' in json.dumps(error)


class SaveConnectGraphQL:

    def __init__(self, api, http: httpx.AsyncClient | None = None):
        self.api = api
        self._owns_http = http is None
        if http is None:
            http = httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(retries=api.http_retries))
        self._http: httpx.AsyncClient = http
        # Error body of the last failed request, for callers that react to specific errors.
        self.last_error = None

    async def write_data_items(self, device_id, register_pair: RegisterWrite, is_import=False):
        """Write one register; returns the API's True/False."""
        variables = {"input": {"dataPoints": [register_pair.dict()]}}
        _LOGGER.debug("Writing data: %s", variables)
        response_data = await self.post_request(REMOTE_API_URL, MUTATION_WRITE_DATA_ITEMS, variables, device_id)
        _LOGGER.debug("Write response: %s", response_data)
        return self.api.data.update(device_id, response_data)

    async def get_data_items_raw(self, device_id, register_ids):
        """Return the raw GetDataItems list (or None) without touching the data store."""
        response_data = await self.post_request(REMOTE_API_URL, QUERY_DATA_ITEMS, {"input": register_ids}, device_id)
        return (response_data or {}).get("GetDataItems")

    async def get_data_items(self, device_id, register_items):
        response_data = await self.post_request(REMOTE_API_URL, QUERY_DATA_ITEMS, {"input": register_items}, device_id)
        return self.api.data.update(device_id, response_data)

    async def export_data_items(self, device_id) -> typing.Optional[list]:
        """The ExportDataItems list (about 300 KB), or None."""
        response_data = await self.post_request(REMOTE_API_URL, QUERY_EXPORT_DATA_ITEMS, {}, device_id)
        items = ((response_data or {}).get("ExportDataItems") or {}).get("dataItems")
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except ValueError:
                return None
        return items if isinstance(items, list) else None

    async def read_data_items(self, device_id, ids=None):
        """Read every register listed in IDREGISTER, or the given ids."""
        status = await self.get_data_items(device_id=device_id, register_items=ids or ALL_REGISTER_IDS)
        if not status:
            _LOGGER.error("GetDataItems failed for %s", device_id)
        return status

    async def get_account(self, with_translations=True) -> typing.List[SaveConnectDevice]:
        """Fetch the account's devices (name, connection and update status) and optionally the UI translations."""
        query = QUERY_DEVICES_AND_TRANSLATIONS if with_translations else QUERY_DEVICES
        response_data = await self.post_request(API_URL, query, {})
        if response_data is None:
            _LOGGER.error("No device data from the API")
            return []

        identifiers = []
        for device_data in response_data["GetAccountDevices"]:
            self.api.data.update_device(device_data=device_data)
            identifiers.append(device_data["identifier"])

        if with_translations:
            for translation_entry in response_data["GetLoggedInUser"]["translations"]:
                self.api.data.update_translations(translation=translation_entry)

        return [self.api.data.devices[identifier] for identifier in identifiers]

    async def post_request(self, url, query, variables, device_id=None, retry=False):
        """POST a GraphQL request; returns the "data" part or None.

        Raises AuthenticationError when logging in again is rejected.
        """
        if not await self.api.ensure_token():
            self.last_error = None
            return None
        headers = {
            "content-type": "application/json",
            "x-access-token": self.api.auth.access_token,
        }
        if device_id:
            headers["Device-Id"] = device_id
            headers["Device-Type"] = "LEGACY"

        try:
            response = await self._http.post(url=url, json=dict(query=query, variables=variables), headers=headers,
                                             timeout=REQUEST_TIMEOUT)
        except httpx.HTTPError as e:
            _LOGGER.warning("Systemair API request failed: %r", e)
            self.last_error = None
            return None

        try:
            response_json = response.json()
        except JSONDecodeError:
            self.last_error = None
            _LOGGER.warning("Could not parse API response (HTTP %s): %s", response.status_code, response.text[:500])
            return None

        if "data" in response_json and not response_json.get("errors"):
            self.last_error = None
            return response_json["data"]

        self.last_error = response_json

        message_key = response_json.get("messageKey") or response_json.get("name")
        _LOGGER.warning("Systemair API error %s: %s", message_key,
                        response_json.get("msg", response_json))
        if not retry and message_key == "UNAUTHORIZED":
            await self.api.ensure_token(force_refresh=True)
            return await self.post_request(url, query, variables, device_id, retry=True)
        return None

    async def close(self):
        if self._owns_http:
            await self._http.aclose()
