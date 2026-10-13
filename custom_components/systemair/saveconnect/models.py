from typing import Dict
from typing import Optional
from typing import Union
from typing import List

from pydantic import BaseModel, Field


class SaveConnectDeviceUnits(BaseModel):
    temperature: str
    pressure: str
    flow: str

class SaveConnectDeviceStatus(BaseModel):
    connectionStatus: str
    startupWizardRequired: bool = None
    updateInProgress: bool = None
    filterLocked: bool = None
    weekScheduleLocked: bool = None
    serviceLocked: bool = None
    hasAlarms: bool = None
    units: SaveConnectDeviceUnits

class SaveConnectRegisterOption(BaseModel):
    title: str
    value: int

class SaveConnectRegisterExtension(BaseModel):
    internalDeviceType: int
    modbusRegister: int
    numberOfRegisters: int

class SaveConnectTime(BaseModel):
    hour: int
    minute: int

class SaveConnectRegisterItem(BaseModel):
    register_: int = Field(alias="id")
    defaultValue: Union[bool, str, int, List, SaveConnectTime]
    options: List[SaveConnectRegisterOption] = None
    readOnly: bool = None
    type: int
    value: Union[bool, str, float, SaveConnectTime, List]
    extension: SaveConnectRegisterExtension

    min: Union[int, SaveConnectTime, List ] = None
    max: Union[int, SaveConnectTime, List ] = None
    unit: int = None
    decimals: int = None
    increment: int = None
    exportable: bool = None
    conditionalProperties: List[Dict] = None

class SaveConnectDeviceType(BaseModel):
    entry: str = None
    module: str = None
    scope: str = None
    type: str = None

from .register import SaveConnectRegistry

# register.py refers to SaveConnectRegisterItem by name to avoid a circular import.
SaveConnectRegistry.model_rebuild(_types_namespace={"SaveConnectRegisterItem": SaveConnectRegisterItem})


class SaveConnectDevice(BaseModel):
    name: str
    identifier: str
    status: SaveConnectDeviceStatus
    startupWizardRequired: str = None
    updateInProgress: str = None
    street: Optional[str] = None
    zipcode: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    serviceLocked: bool = None
    filterLocked: bool = None
    weekScheduleLocked: bool = None
    hasAlarms: bool = None
    deviceType: SaveConnectDeviceType = None
    registry: SaveConnectRegistry = None
    cb: Optional[list] = []

    def add_update_callback(self, cb):
        self.cb.append(cb)


def update(self, data: Dict):
    for k, v in data.items():
        setattr(self, k, v)
    return self
