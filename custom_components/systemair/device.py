"""Home Assistant side wrapper around one SaveConnect device."""
from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from homeassistant.const import UnitOfTemperature
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, MANUFACTURER, PRESETS
from .saveconnect import AuthenticationError, SaveConnect
from .saveconnect.const import IdCheck
from .saveconnect.data import effective_item
from .saveconnect.models import SaveConnectDevice, SaveConnectRegisterItem

if TYPE_CHECKING:
    from .coordinator import SystemairCoordinator

_LOGGER = logging.getLogger(__name__)

DIGITAL_OUTPUTS = range(1, 5)
COOLING_OUTPUT_TYPE = "VIEWS_SERVICE_OUTPUT_DIGITAL_TYPES_P1COOLING"
UNIVERSAL_INPUTS = range(1, 7)
TEMPERATURE_INPUTS = range(1, 8)
# Unit functions the unit reports as active (as shown in the app), with display names.
ACTIVE_FUNCTIONS = {
    "REG_FUNCTION_ACTIVE_COOLING": "Cooling",
    "REG_FUNCTION_ACTIVE_FREE_COOLING": "Free cooling",
    "REG_FUNCTION_ACTIVE_HEATING": "Heating",
    "REG_FUNCTION_ACTIVE_DEFROSTING": "Defrosting",
    "REG_FUNCTION_ACTIVE_HEAT_RECOVERY": "Heat recovery",
    "REG_FUNCTION_ACTIVE_COOLING_RECOVERY": "Cooling recovery",
    "REG_FUNCTION_ACTIVE_MOISTURE_TRANSFER": "Moisture transfer",
    "REG_FUNCTION_ACTIVE_SECONDARY_AIR": "Secondary air",
    "REG_FUNCTION_ACTIVE_VACUUM_CLEANER": "Vacuum cleaner",
    "REG_FUNCTION_ACTIVE_COOKER_HOOD": "Cooker hood",
    "REG_FUNCTION_ACTIVE_USER_LOCK": "User lock",
    "REG_FUNCTION_ACTIVE_ECO_MODE": "Eco mode",
    "REG_FUNCTION_ACTIVE_HEATER_COOL_DOWN": "Heater cool down",
    "REG_FUNCTION_ACTIVE_PRESSURE_GUARD": "Pressure guard",
    "REG_FUNCTION_ACTIVE_CDI_1": "Configurable DI 1",
    "REG_FUNCTION_ACTIVE_CDI_2": "Configurable DI 2",
    "REG_FUNCTION_ACTIVE_CDI_3": "Configurable DI 3",
}


def option_key(title: str) -> str:
    """Stable state for a SaveConnect option title, e.g. VIEWS_SERVICE_INPUT_NOT_SET -> input_not_set.

    Option titles are SaveConnect translation keys, so they do not change with
    the account language; the labels shown come from the integration's translations.
    """
    key = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    return key.removeprefix("views_service_").removesuffix("_title") or "none"


def option_keys(options) -> dict[str, int]:
    """State key -> register value for a register's options (titles that map to one key get the value appended)."""
    keys: dict[str, int] = {}
    for option in options or []:
        key = option_key(option.title)
        if key in keys:
            key = f"{key}_{option.value}"
        keys.setdefault(key, option.value)
    return keys


class SystemairDevice:
    """Reads values from the device registry and performs writes."""

    def __init__(self, api: SaveConnect, device: SaveConnectDevice) -> None:
        self.api = api
        self.device = device
        self.coordinator: SystemairCoordinator | None = None
        # Registers read by entities; the regular poll fetches only these.
        self.used_registers: set[str] = set()
        # Result of comparing the register id table with the unit at setup.
        self.id_check: IdCheck | None = None

    @property
    def device_id(self) -> str:
        return self.device.identifier

    @property
    def name(self) -> str:
        return self.device.name

    @property
    def registry(self):
        return self.device.registry

    @property
    def online(self) -> bool:
        return self.device.status.connectionStatus == "ONLINE"

    def register(self, name: str):
        self.used_registers.add(name)
        return getattr(self.registry, name, None)

    def value(self, name: str) -> Any:
        reg = self.register(name)
        return None if reg is None else reg.value

    def properties(self, name: str) -> SaveConnectRegisterItem | None:
        """The register with its conditional unit/range/decimals applied.

        The registers the conditions refer to are polled from then on as well.
        """
        reg = self.register(name)
        if reg is None:
            return None

        def value_of(item_id: int) -> Any:
            other = self.api.data.name_by_id(self.device_id, item_id)
            return self.value(other) if other else None

        return effective_item(reg, value_of)

    def int_value(self, name: str) -> int | None:
        value = self.value(name)
        if value is None or value == "":
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    def bool_value(self, name: str) -> bool | None:
        value = self.value(name)
        if value is None or value == "":
            return None
        if isinstance(value, str):
            return value.lower() in ("true", "1")
        return bool(value)

    @property
    def temperature_unit(self) -> str:
        """The unit's temperature unit; temperature registers hold tenths of it."""
        return UnitOfTemperature.FAHRENHEIT if self.int_value("REG_SYSTEM_UNIT_TEMPERATURE") == 1 else UnitOfTemperature.CELSIUS

    def active_functions(self) -> list[str]:
        """Names of the unit functions currently active, e.g. ["Heat recovery"]."""
        return [label for register, label in ACTIVE_FUNCTIONS.items() if self.bool_value(register)]

    def translate(self, key: str) -> str:
        return self.api.translations.get(key, key)

    def option_title(self, name: str) -> str | None:
        """Untranslated title of the register's current option."""
        reg = self.register(name)
        value = self.int_value(name)
        if reg is None or value is None or not reg.options:
            return None
        return next((o.title for o in reg.options if o.value == value), None)

    def option_state(self, name: str) -> str | None:
        """Stable state key of the register's current option."""
        reg = self.register(name)
        value = self.int_value(name)
        if reg is None or value is None or not reg.options:
            return None
        return next((key for key, v in option_keys(reg.options).items() if v == value), None)

    def _version(self, prefix: str, suffix: str = "") -> str | None:
        parts = [self.int_value(f"{prefix}_{part}{suffix}") for part in ("MAJOR", "MINOR", "BUILD")]
        if None in parts:
            return None
        return ".".join(map(str, parts))

    @property
    def model(self) -> str | None:
        return self.value("REG_SYSTEM_UNIT_MODEL1")

    @property
    def serial_number(self) -> str | None:
        return self.value("REG_SYSTEM_SERIAL_NUMBER1")

    @property
    def main_board_version(self) -> str | None:
        return self._version("REG_PU_RUNNING_VERSION")

    @property
    def iam_version(self) -> str | None:
        return self._version("REG_PU_RUNNING_VERSION", "_IAM")

    @property
    def hmi_version(self) -> str | None:
        """Running version of the control panel."""
        return self._version("REG_PU_RUNNING_VERSION", "_HMI")

    @property
    def main_board_flash_version(self) -> str | None:
        """Main board firmware image held by the IAM, ready to install."""
        return self._version("REG_PU_FLASH_VERSION_MB")

    @property
    def hmi_flash_version(self) -> str | None:
        """Control panel firmware image held by the IAM, ready to install."""
        return self._version("REG_PU_FLASH_VERSION_HMI")

    @property
    def update_in_progress(self) -> bool:
        return bool(self.device.status.updateInProgress)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            manufacturer=MANUFACTURER,
            name=self.name,
            model=self.model,
            serial_number=self.serial_number,
            sw_version=self.iam_version,
            hw_version=self.main_board_version,
        )

    @property
    def user_mode(self) -> int | None:
        """Current preset, 0 = Auto ... 6 = Holiday."""
        return self.int_value("REG_USERMODE_MODE_HMI")

    @property
    def preset(self) -> str | None:
        """Current preset name; the unit reports some Manual variants as extra mode values."""
        title = self.option_title("REG_USERMODE_MODE_HMI")
        if title is None:
            return None
        name = title.removeprefix("USER_MODES_").removesuffix("_TITLE").capitalize()
        return name if name in PRESETS else None

    @property
    def airflow_level(self) -> int | None:
        """Actual airflow level, index into AIRFLOW_LEVELS."""
        return self.int_value("REG_SPEED_INDICATION_APP")

    def cooling_output(self) -> str | None:
        """Name of the digital output register configured for the cooling pump, if any."""
        for n in DIGITAL_OUTPUTS:
            if self.option_title(f"REG_DO_CFG_CONNECTION_{n}") == COOLING_OUTPUT_TYPE:
                return f"REG_OUTPUT_DO{n}"
        return None

    def universal_inputs(self, function: str) -> list[int]:
        """Universal inputs configured as the given analog sensor, e.g. "CO2" or "RH"."""
        return [
            n for n in UNIVERSAL_INPUTS
            if self.option_title(f"REG_UI_CFG_TYPE_{n}") == "VIEWS_SERVICE_INPUT_ANALOG_SELECTION"
            and self.option_title(f"REG_UI_CONNECTION_ANALOG{n}") == f"VIEWS_SERVICE_INPUT_UNIVERSAL_VALUES_{function}_TITLE"
        ]

    def has_temperature_input(self, function: str) -> bool:
        """Whether a temperature (NTC) input is configured as the given sensor, e.g. "RAT"."""
        title = f"VIEWS_SERVICE_INPUT_ANALOG_VALUES_{function}_TITLE"
        return any(self.option_title(f"REG_AI_CFG_CONNECTION_NTC{n}") == title for n in TEMPERATURE_INPUTS)

    async def async_write_register(self, name: str, value, allow_read_only: bool = False) -> None:
        await self._write(name, self.api.write_register(self.device, name, value, allow_read_only))

    async def async_set_preset(self, preset: str) -> None:
        mode = PRESETS[preset]

        def show_new_mode() -> None:
            # The change request register is write-only; reflect the new mode right away.
            if (reg := self.register("REG_USERMODE_MODE_HMI")) is not None:
                self.api.data.apply_items(self.device_id, [{"id": reg.register_, "value": str(mode)}])

        await self._write(f"preset {preset}", self.api.set_preset(self.device, mode), show_new_mode)

    async def async_set_manual_airflow(self, value: int) -> None:
        await self.async_write_register("REG_USERMODE_MANUAL_AIRFLOW_LEVEL_SAF", str(value))

    async def async_set_temperature(self, temperature: float) -> None:
        await self.async_write_register("REG_TC_SP", str(int(round(temperature * 10))))

    async def _write(self, what: str, write: Awaitable[bool], on_success: Callable[[], None] | None = None) -> None:
        """Run a write and turn its outcome into Home Assistant errors."""
        try:
            success = await write
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        except AuthenticationError as err:
            if self.coordinator:
                self.coordinator.config_entry.async_start_reauth(self.coordinator.hass)
            raise HomeAssistantError("SaveConnect rejected the login; re-authenticate the integration") from err
        if not success:
            raise HomeAssistantError(f"Writing {what} to {self.name} failed")
        if on_success:
            on_success()
        if self.coordinator:
            self.coordinator.after_write()
