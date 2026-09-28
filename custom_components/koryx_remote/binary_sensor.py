"""Estado da conexão de saída."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
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
    async_add_entities([KoryxConnectedSensor(entry, link)])


class KoryxConnectedSensor(BinarySensorEntity):
    """Ligado quando o HA está alcançável de fora."""

    _attr_has_entity_name = True
    _attr_name = "Conectado"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, link: KoryxLink) -> None:
        self._link = link
        self._attr_unique_id = f"{entry.entry_id}_connected"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Koryx Remote",
            configuration_url=str(entry.data.get(CONF_URL) or ""),
        )

    @property
    def is_on(self) -> bool:
        return self._link.connected

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._link.add_listener(self.schedule_update_ha_state))
