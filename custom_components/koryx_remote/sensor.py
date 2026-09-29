"""Data de expiração do trial, visível dentro do Home Assistant.

A ideia é o usuário não precisar abrir o painel para saber quanto tempo resta:
a entidade aparece no dispositivo Koryx Remote, no próprio HA, no mesmo lugar
onde ele já vê se a casa está ligada. Os atributos (`plan`, `days_remaining`,
`status`) alimentam automação e cartão sem parsing de texto.
"""

from __future__ import annotations

from datetime import UTC, datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import KoryxLink
from .const import CONF_URL, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    link: KoryxLink = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([KoryxTrialSensor(entry, link)])


class KoryxTrialSensor(SensorEntity):
    """Quando o trial termina. Sem plano pago, é o que desliga a casa."""

    _attr_has_entity_name = True
    _attr_name = "Trial termina em"
    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, entry: ConfigEntry, link: KoryxLink) -> None:
        self._link = link
        self._attr_unique_id = f"{entry.entry_id}_trial_ends_at"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Koryx Remote",
            configuration_url=str(entry.data.get(CONF_URL) or ""),
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._link.add_listener(self.schedule_update_ha_state))

    @property
    def native_value(self) -> datetime | None:
        if self._link.plan == "basic":
            return None
        return self._link.trial_ends_at

    @property
    def extra_state_attributes(self) -> dict[str, str | int | None]:
        plan = self._link.plan
        ends_at = self._link.trial_ends_at
        if plan == "basic":
            return {"plan": plan, "status": "active", "days_remaining": None}
        if ends_at is None:
            return {"plan": plan, "status": "unknown", "days_remaining": None}
        remaining = ends_at - datetime.now(UTC)
        seconds = remaining.total_seconds()
        status = "active" if seconds > 0 else "expired"
        days = max(0, -(-int(seconds) // 86_400)) if seconds > 0 else 0
        return {"plan": plan, "status": status, "days_remaining": days}
