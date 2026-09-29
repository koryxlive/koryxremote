"""Plano e vencimento, visíveis dentro do Home Assistant.

A ideia é o usuário não precisar abrir o painel para saber o que tem: a
entidade aparece no dispositivo Koryx Remote, no mesmo lugar onde ele já vê se
a casa está ligada. Os atributos (`plan`, `status`, `days_remaining`) alimentam
automação e cartão sem parsing de texto.

São duas entidades porque são duas perguntas — "qual é o meu plano?" e "até
quando?" — e o nome delas precisa servir tanto quem está no trial quanto quem
já paga. Um nome fixo como "Trial termina em" mentiria para o cliente pagante,
que é justamente quem menos quer ler isso.
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
    async_add_entities([KoryxPlanSensor(entry, link), KoryxExpirySensor(entry, link)])


class KoryxBaseSensor(SensorEntity):
    """Base: dispositivo, escuta de mudança e o `link` compartilhado."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, link: KoryxLink, key: str, name: str) -> None:
        self._link = link
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Koryx Remote",
            configuration_url=str(entry.data.get(CONF_URL) or ""),
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._link.add_listener(self.schedule_update_ha_state))


class KoryxPlanSensor(KoryxBaseSensor):
    """O plano atual. `Trial` ou `Básico`, do jeito que a pessoa lê."""

    _attr_icon = "mdi:account-star"

    def __init__(self, entry: ConfigEntry, link: KoryxLink) -> None:
        super().__init__(entry, link, "plan", "Plano")

    @property
    def native_value(self) -> str:
        return self._link.plan_label

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        # O id cru vai junto: automação usa a chave estável, não o rótulo, que
        # pode ser traduzido sem aviso.
        return {"plan_id": self._link.plan}


class KoryxExpirySensor(KoryxBaseSensor):
    """Até quando o acesso vale — trial ou assinatura."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, entry: ConfigEntry, link: KoryxLink) -> None:
        super().__init__(entry, link, "expiry", "Vence em")

    @property
    def native_value(self) -> datetime | None:
        return self._link.expiry

    @property
    def extra_state_attributes(self) -> dict[str, str | int | None]:
        plan = self._link.plan
        ends_at = self._link.expiry
        base = {"plan": plan, "plan_label": self._link.plan_label}
        if ends_at is None:
            # Plano pago sem data de renovação no servidor (não há billing).
            # "sem_vencimento" é a verdade; "unknown" faria parecer falha.
            return {**base, "status": "sem_vencimento", "days_remaining": None}
        remaining = ends_at - datetime.now(UTC)
        seconds = remaining.total_seconds()
        status = "active" if seconds > 0 else "expired"
        days = max(0, -(-int(seconds) // 86_400)) if seconds > 0 else 0
        return {**base, "status": status, "days_remaining": days}
