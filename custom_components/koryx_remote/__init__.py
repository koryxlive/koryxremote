"""Koryx Remote no Home Assistant."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback

from .client import KoryxLink
from .const import CONF_URL, DOMAIN
from .update_check import KoryxUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["binary_sensor", "sensor", "update"]


@dataclass
class _EntryState:
    """O que esta entry mantém vivo entre setup, update de opções e unload.

    Guardar tudo num objeto por entry, em vez de espalhar chaves soltas no
    `hass.data[DOMAIN]`, evita a colisão que já existiria aqui: o unsubscriber
    do Report State e o `entry_id` do link iam para o mesmo dict, e a segunda
    entry sobrescreveria o unsubscriber da primeira.
    """

    link: KoryxLink
    update_coordinator: KoryxUpdateCoordinator
    report_state_unsub: CALLBACK_TYPE | None = field(default=None)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    public_url = entry.data.get(CONF_URL)
    if isinstance(public_url, str) and public_url.startswith("https://"):
        # `async_update` é coroutine: sem o `await` ela nunca roda, a URL
        # externa não é gravada e o HA loga
        # "coroutine 'Config.async_update' was never awaited" a cada setup.
        await hass.config.async_update(external_url=public_url)
    coordinator = KoryxUpdateCoordinator(hass, entry)
    state = _EntryState(link=KoryxLink(hass, entry), update_coordinator=coordinator)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = state
    # Primeira leitura antes das plataformas. Só `async_refresh`: se
    # GitHub/API falharem, a entry sobe mesmo assim — o túnel não depende
    # do check de versão (first_refresh em falha marcaria a entry not ready).
    await coordinator.async_refresh()

    # Corrige o `powerState` de `cover`: o core deriva `state != "off"`, e
    # `closed` não é `off`, então a cortina fechada aparecia como "Ativada" no
    # app e nenhum `ChangeReport` saía. Troca o adapter de `cover` no registry
    # do core por um que reporta OFF em `closed`.
    # Ver `alexa._install_cover_power_override`.
    from .alexa import _install_cover_power_override

    _install_cover_power_override()

    # Painel da sidebar: a escolha de dispositivos ganha busca e filtro por
    # domínio, que o formulário nativo do HA não oferece. Ver `panel.py` para
    # o porquê de existir um painel além do OptionsFlow (os dois leem e
    # gravam a MESMA `entry.options["exposed_entities"]`).
    #
    # **O painel é opcional, o túnel não.** Este `await` roda antes do link
    # subir e daqui do `async_setup_entry`, então uma exceção aqui derruba a
    # entry inteira: o HA mostra "falha ao configurar", a casa fica fora do ar
    # e o sintoma (`503 AGENT_OFFLINE`) não aponta para o painel. Aconteceu de
    # verdade na 0.2.18 (barra final no `StaticPathConfig`, `AssertionError`
    # do aiohttp). Um recurso de conveniência não pode levar o túnel junto.
    from .panel import async_setup_panel

    try:
        await async_setup_panel(hass)
    except Exception:  # noqa: BLE001 — ver o comentário acima: nada aqui derruba o túnel
        _LOGGER.exception(
            "Koryx Remote: falha ao registrar o painel da sidebar. "
            "O túnel e os sensores seguem funcionando; a seleção de dispositivos "
            "continua disponível pelo OptionsFlow."
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Report State proativo: o core só liga o listener no `AcceptGrant`, e o
    # nosso caminho (`supports_auth = False`) nunca passa por lá. Ver o
    # docstring de `async_enable_report_state` para o porquê em detalhe.
    await _async_refresh_report_state(hass, entry, state)

    # **Background task**, e não `hass.async_create_task`: a task normal (1) é
    # contada no bootstrap — o HA logava "Setup timed out for bootstrap waiting
    # on KoryxLink.run()", porque o `run()` só termina quando a casa desliga —
    # e (2) não é cancelada no shutdown, o que fazia o HA reclamar que a task
    # "was still running after final writes shutdown stage". A background task
    # não bloqueia o startup e o HA cancela sozinho no shutdown e no unload.
    entry.async_create_background_task(hass, state.link.run(), f"{DOMAIN} link")

    # Parada cooperativa: em vez de depender só do cancelamento, fechamos o
    # WebSocket quando o HA começa a desligar. O `run()` vê o `_stop` e sai
    # sozinho, sem ficar preso num `await` de rede durante a finalização.
    @callback
    def _stop_on_shutdown(_event: Event) -> None:
        hass.async_create_task(state.link.async_stop())

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _stop_on_shutdown))
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    # Desligar o listener proativo no unload é responsabilidade do unsubscriber
    # que `async_enable_report_state` devolveu — guardado no `state`, não no
    # registro de `async_on_unload`, para podermos trocá-lo a cada update sem
    # acumular callbacks de unload que nunca seriam descartados.
    entry.async_on_unload(lambda: state.report_state_unsub and state.report_state_unsub())
    return True


async def _async_refresh_report_state(
    hass: HomeAssistant, entry: ConfigEntry, state: _EntryState
) -> None:
    """(Re)configura o listener proativo para o `report_state` atual.

    Desliga o antigo **antes** de decidir o novo. Sem isto, um update de opções
    que só mexeu na seleção de entidades (com `report_state` seguindo ligado)
    registraria um segundo listener, e cada mudança de estado geraria dois
    `ChangeReport` — a Alexa receberia o mesmo evento em duplicidade.
    """
    if state.report_state_unsub is not None:
        state.report_state_unsub()
        state.report_state_unsub = None

    from .alexa import async_enable_report_state

    state.report_state_unsub = await async_enable_report_state(hass, entry)


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Listener de `options`: o HA exige uma coroutine aqui, não uma função.

    O `KoryxAlexaConfig` lê a seleção do `entry.options` a cada directive, então
    não há cache para invalidar do lado da Alexa — só avisar a API de que a
    lista mudou. O `report_state` é o único option com efeito colateral em
    runtime, e é tratado no `_async_refresh_report_state`.
    """
    state: _EntryState | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if state is None:
        return
    await _async_refresh_report_state(hass, entry, state)
    await state.link.notify_entities_changed()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        # Só remove o painel quando NÃO sobra entry nenhuma: com duas casas, a
        # saída de uma não deve apagar o item da sidebar da outra.
        if not hass.data.get(DOMAIN):
            from .panel import async_unregister_panel

            async_unregister_panel(hass)
    return unloaded
