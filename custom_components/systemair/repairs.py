"""Repair notices for register id problems."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN, ISSUE_TRACKER
from .device import SystemairDevice


def update_register_id_issue(hass: HomeAssistant, device: SystemairDevice) -> None:
    """Show (or clear) a repair notice when ids differ from the table or reads skip unknown ids."""
    check = device.id_check
    changed = sorted(check.changed) if check else []
    missing = sorted(check.missing) if check else []
    gone = sorted(device.api.missing_ids(device.device_id))
    issue_id = f"register_ids_{device.device_id}"
    if not (changed or missing or gone):
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="register_ids",
        translation_placeholders={
            "device": device.name,
            "changed": ", ".join(changed) or "-",
            "missing": ", ".join(missing) or "-",
            "gone": ", ".join(map(str, gone)) or "-",
            "url": ISSUE_TRACKER,
        },
        learn_more_url=ISSUE_TRACKER,
    )
