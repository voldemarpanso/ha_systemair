import json
import logging
import typing

from .models import SaveConnectDevice, SaveConnectRegisterItem, SaveConnectTime, update
from .register import Register, SaveConnectRegistry

_LOGGER = logging.getLogger(__name__)


def _like(current, value):
    """A value-only update in the shape of the current value (hour:minute values arrive as JSON or dicts)."""
    if isinstance(current, SaveConnectTime) and not isinstance(value, SaveConnectTime):
        try:
            return SaveConnectTime.model_validate(json.loads(value) if isinstance(value, str) else value)
        except ValueError:
            return current
    return value


def register_name(item: dict) -> typing.Optional[str]:
    """Registry attribute name for a raw data item, e.g. "REG_TC_SP" or "REG_PU_RUNNING_VERSION_MAJOR_IAM"."""
    ext = item["extension"]
    key = str(ext["modbusRegister"])
    if ext["internalDeviceType"] > 1:
        key += f"-{ext['internalDeviceType']}"
    return Register.map.get(key)


def _condition_holds(condition: dict, value) -> bool:
    if value is None or isinstance(value, (list, dict)) or hasattr(value, "model_dump"):
        return False
    try:
        value = int(float(value))
    except (TypeError, ValueError):
        return False
    return (value in condition.get("values", [])) == condition.get("equalityOperator", True)


def effective_item(item: SaveConnectRegisterItem,
                   value_of: typing.Callable[[int], typing.Any]) -> SaveConnectRegisterItem:
    """The item with its conditionalProperties applied.

    Some registers change unit, range or decimals with other settings (e.g. an
    input correction is in ppm for a CO2 sensor and in % for a humidity
    sensor). Each rule lists conditions on other data items by id; the
    properties of every rule that holds are applied in order. value_of maps a
    data item id to its current value (None when unknown).
    """
    properties = {}
    for rule in item.conditionalProperties or []:
        results = [_condition_holds(c, value_of(c.get("dataItemId"))) for c in rule.get("conditions", [])]
        if results and (any(results) if rule.get("logic") == "or" else all(results)):
            properties.update(rule.get("properties", {}))
    return item.model_copy(update=properties) if properties else item


class SaveConnectData:

    def __init__(self):
        self.devices: typing.Dict[str, SaveConnectDevice] = dict()
        self.translations: typing.Dict[str, str] = dict()
        # Registry name per data item id, per device.
        self._names_by_id: typing.Dict[str, typing.Dict[int, str]] = dict()

    def update_translations(self, translation):
        self.translations[translation['key']] = translation['value']

    def update_device(self, device_data):
        """Add a device from GetAccountDevices, or refresh an existing one's fields (keeping its registry)."""
        device_id = device_data["identifier"]
        existing = self.devices.get(device_id)
        parsed = SaveConnectDevice.model_validate({
            **device_data,
            "registry": existing.registry if existing else SaveConnectRegistry(),
        })
        if existing is None:
            self.devices[device_id] = parsed
        else:
            update(existing, {key: getattr(parsed, key) for key in device_data})

    def update(self, device_id, data):
        """Apply a GraphQL response: WriteDataItems -> its bool, GetDataItems -> registers stored."""
        if data is None:
            return False
        if "WriteDataItems" in data:
            return data["WriteDataItems"]
        if "GetDataItems" in data:
            return self.apply_items(device_id, data["GetDataItems"])
        _LOGGER.debug("Unexpected response data: %s", data)
        return False

    def apply_items(self, device_id, items) -> bool:
        """Store data items for a device and notify its callbacks.

        Items normally carry full metadata (id, value, extension, options...).
        Items with only id and value, as push events may send, update the
        value of a register already known by that id.
        """
        device = self.devices.get(device_id)
        if device is None:
            _LOGGER.debug("Ignoring data for unknown device %s", device_id)
            return False
        if not items:
            return False

        registry = device.registry
        by_id = self._names_by_id.setdefault(device_id, {})
        changed = {}
        for item in items:
            if "extension" in item:
                name = register_name(item)
                if name is None:
                    continue
                changed[name] = SaveConnectRegisterItem.model_validate(item)
                by_id[changed[name].register_] = name
                continue

            name = by_id.get(item.get("id"))
            if name is None:
                continue
            current = getattr(registry, name)
            changed[name] = current.model_copy(update={"value": _like(current.value, item["value"])})

        update(registry, changed)
        _LOGGER.debug("Updated %d registers for device %s", len(changed), device_id)

        for cb in device.cb:
            for reg in changed.values():
                cb(reg.extension.modbusRegister, reg.value, reg)
        return True

    def name_by_id(self, device_id, item_id) -> typing.Optional[str]:
        """Registry name of a data item id already read for the device."""
        return self._names_by_id.get(device_id, {}).get(item_id)

    def effective_item(self, device: SaveConnectDevice, name: str) -> typing.Optional[SaveConnectRegisterItem]:
        """The register with its conditional properties applied (see effective_item)."""
        item = getattr(device.registry, name, None)
        if item is None:
            return None

        def value_of(item_id):
            other = self.name_by_id(device.identifier, item_id)
            reg = getattr(device.registry, other, None) if other else None
            return None if reg is None else reg.value

        return effective_item(item, value_of)

    def update_status(self, device_id, properties) -> bool:
        """Apply a DEVICE_STATUS_UPDATE summary to the device status."""
        device = self.devices.get(device_id)
        if device is None:
            return False
        if "update" in properties:
            device.status.updateInProgress = bool(properties["update"].get("inProgress"))
        if "activeAlarms" in properties:
            device.status.hasAlarms = bool(properties["activeAlarms"])
        return True

    def set_availability(self, device_id, available):
        if device_id not in self.devices:
            return
        self.devices[device_id].status.connectionStatus = "ONLINE" if available else "OFFLINE"

    def get_device(self, device_id):
        return self.devices[device_id]
