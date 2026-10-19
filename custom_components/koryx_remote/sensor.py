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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .client import KoryxLink
from .const import CONF_URL, DOMAIN, MANUFACTURER
from .update_check import KoryxUpdateCoordinator, UpdateInfo


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    state = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            KoryxPlanSensor(entry, state.link),
            KoryxExpirySensor(entry, state.link),
            KoryxVersionSensor(entry, state.update_coordinator),
        ]
    )


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
            manufacturer=MANUFACTURER,
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
    """Até quando o acesso vale — trial ou assinatura.

    O `unique_id` é `..._trial`, herdado da entidade `0.1.4` que se chamava
    "Trial termina em". Não é descuido: no HA a entidade é o `unique_id`, então
    reaproveitá-lo faz o registry **renomear** a existente. Com um id novo, o HA
    registraria outra e a antiga ficaria órfã no registry — visível e
    "Indisponível" na tela do dispositivo, apontando para um objeto que não
    existe mais. O nome pode mudar à vontade; o id, não.
    """

    _attr_icon = "mdi:calendar-clock"

    def __init__(self, entry: ConfigEntry, link: KoryxLink) -> None:
        super().__init__(entry, link, "trial", "Vence em")

    @property
    def device_class(self) -> SensorDeviceClass | None:
        """Timestamp só quando há data; sem data o HA não sabe renderizar `None`.

        Um `device_class` de timestamp exige data/hora. Com `native_value` nulo
        o HA não mostra vazio: mostra "Desconhecido", como se o dado tivesse
        falhado. No plano pago o `device_class` sai e o valor vira
        "Sem vencimento" — que é a verdade, sem parecer erro.
        """
        return None if self._link.expiry is None else SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> datetime | str | None:
        if self._link.expiry is None:
            # Conta sem prazo gravado no servidor: o admin não preencheu a data
            # do plano pago ainda. O texto ocupa o lugar da data para a tela
            # dizer algo verdadeiro, em vez de "Desconhecido". O valor literal
            # não leva acento nem caixa alta porque o HA o usa em automação e
            # na URL de histórico.
            return "sem_vencimento"
        return self._link.expiry

    @property
    def extra_state_attributes(self) -> dict[str, str | int | None]:
        plan = self._link.plan
        ends_at = self._link.expiry
        base = {"plan": plan, "plan_label": self._link.plan_label}
        if ends_at is None:
            # Sem prazo gravado. "sem_vencimento" é a verdade; "unknown" faria
            # parecer que o dado falhou.
            return {**base, "status": "sem_vencimento", "days_remaining": None}
        remaining = ends_at - datetime.now(UTC)
        seconds = remaining.total_seconds()
        status = "active" if seconds > 0 else "expired"
        days = max(0, -(-int(seconds) // 86_400)) if seconds > 0 else 0
        return {**base, "status": status, "days_remaining": days}


class KoryxVersionSensor(CoordinatorEntity[KoryxUpdateCoordinator], SensorEntity):
    """Versão instalada, com a publicada nos atributos (para automação).

    O cartão visual de update é o `update.koryx_remote_*`. Este sensor existe
    para quem quer template/automação sem parsear a entidade update — estado =
    instalada; `latest_version` / `update_available` nos atributos.
    """

    _attr_has_entity_name = True
    _attr_name = "Versão"
    _attr_icon = "mdi:package-variant"

    def __init__(self, entry: ConfigEntry, coordinator: KoryxUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_version"
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
    def native_value(self) -> str | None:
        return self._info.installed if self._info else None

    @property
    def extra_state_attributes(self) -> dict[str, str | bool | None]:
        info = self._info
        if info is None:
            return {"latest_version": None, "update_available": False, "release_url": None}
        return {
            "latest_version": info.latest,
            "update_available": info.available,
            "release_url": info.release_url,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
