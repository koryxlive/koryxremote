"""Entidade `update` — o cartão nativo de “há versão nova” do HA."""

from __future__ import annotations

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_URL, DOMAIN, MANUFACTURER
from .update_check import KoryxUpdateCoordinator, UpdateInfo


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: KoryxUpdateCoordinator = hass.data[DOMAIN][entry.entry_id].update_coordinator
    async_add_entities([KoryxUpdateEntity(entry, coordinator)])


class KoryxUpdateEntity(CoordinatorEntity[KoryxUpdateCoordinator], UpdateEntity):
    """Mostra instalada vs publicada; sem botão de instalar (vai pelo HACS)."""

    _attr_has_entity_name = True
    _attr_name = "Atualização"
    _attr_title = "Koryx Remote"
    # Sem INSTALL: baixar zip e reiniciar pelo botão do HA é frágil e
    # atropela o HACS. O cartão só informa; o push aponta o caminho.
    _attr_supported_features = UpdateEntityFeature(0)

    def __init__(self, entry: ConfigEntry, coordinator: KoryxUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_update"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Koryx Remote",
            manufacturer=MANUFACTURER,
            configuration_url=str(entry.data.get(CONF_URL) or ""),
        )

    @property
    def _info(self) -> UpdateInfo | None:
        return self.coordinator.data

    @property
    def installed_version(self) -> str | None:
        return self._info.installed if self._info else None

    @property
    def latest_version(self) -> str | None:
        if not self._info:
            return None
        # Sem latest conhecido, o HA trata como "em dia" se latest == installed.
        return self._info.latest or self._info.installed

    @property
    def release_url(self) -> str | None:
        return self._info.release_url if self._info else None

    @property
    def release_summary(self) -> str | None:
        if not self._info or not self._info.available:
            return None
        return (
            f"Versão {self._info.latest} disponível. "
            "Atualize pelo HACS e reinicie o Home Assistant."
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
