"""Painel da sidebar para escolher os dispositivos que a Alexa enxerga.

Por que um painel, e nao o OptionsFlow que ja existe
----------------------------------------------------

O `EntitySelector` do HA e o teto do formulario nativo: ele da busca e
selecao multipla, mas **nao** da filtro por dominio em forma de abas. O
`filter` do HA so *restringe* a lista em silencio — nao desenha chip
clicavel. Testamos as duas formas (config unica e lista de configs por
dominio) e a UI nao muda. Ver `config_flow.KoryxRemoteOptionsFlow`.

Numa casa com 141 `light` + 11 `cover` + 7 `climate`, procurar na lista
misturada e pior que poder dizer "so cortinas" antes de digitar. O painel
resolve isso com o que o formulario nao tem: busca, filtro por dominio e
selecao que sobrevive a troca de filtro.

O OptionsFlow **continua existindo** e e a fonte de verdade dos dados: o
painel le e grava exatamente `entry.options["exposed_entities"]`. Quem
preferir o formulario nativo (ou estiver num cliente que nao carrega o
painel) segue atendido — nao ha uma segunda copia da selecao em lugar
nenhum.
"""

from __future__ import annotations

import logging
import os

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Onde o bundle do painel e servido. O HA monta arquivos estaticos sob
# `/api/...`; usar o proprio DOMAIN evita colisao com outra integracao e
# deixa claro de quem e o arquivo ao olhar a aba de rede do browser.
#
# **SEM barra final.** O `web.StaticResource` do aiohttp recebe este valor como
# `prefix`, e o `__init__` do aiohttp tem uma assercao literal contra barra no
# fim: `assert prefix in ("", "/") or not prefix.endswith("/")`. Com a barra,
# `async_register_static_paths` estoura `AssertionError`, e como isso roda
# dentro do `async_setup_entry`, a entry INTEIRA falha ao configurar — o HA
# mostra "falha ao configurar" e o tunel nem sobe. Foi exatamente o que
# aconteceu na 0.2.18. O aiohttp normaliza o prefixo sem barra para casar com
# `/koryx-remote-panel/arquivo.js`, entao a barra nunca foi necessaria.
PANEL_URL_PATH = f"{DOMAIN}-panel"
PANEL_JS = "koryx-remote-panel.js"

# `webcomponent_name` precisa bater **exatamente** com o nome passado ao
# `customElements.define()` la no JS. Se divergir, o painel registra mas o
# frontend nao acha o elemento e a pagina fica em branco — sem erro obvio.
WEBCOMPONENT_NAME = "koryx-remote-panel"

# `frontend_url_path` e o que aparece na URL: `/koryx-remote`.
FRONTEND_URL_PATH = "koryx-remote"

# `mdi:amazon-alexa` saiu do MDI (icone removido por marca registrada): o
# painel registrava, mas a sidebar desenhava o item sem icone. `mdi:cast-audio`
# e generico e continua no set atual.
SIDEBAR_ICON = "mdi:cast-audio"


async def async_register_panel(hass: HomeAssistant) -> None:
    """Registra o painel uma vez, na primeira entry que subir.

    Idempotente de proposito: com duas casas ligadas na mesma conta,
    `async_setup_entry` roda duas vezes e um segundo registro faria o HA
    logar "Overwriting panel". O marcador mora no `hass.data` porque o
    registro do painel tambem.
    """
    if hass.data.get(f"{DOMAIN}_panel_registered"):
        return
    hass.data[f"{DOMAIN}_panel_registered"] = True

    frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
    # `cache_headers=False`: durante o desenvolvimento do painel, um bundle
    # cacheado faz a mudanca "nao aparecer" — que e exatamente o sintoma que
    # nos custou tempo antes. O arquivo e pequeno; o custo de rebaixar e
    # menor que o de depurar cache.
    #
    # Sem barra final: o aiohttp rejeita `prefix` terminado em `/` com
    # `AssertionError`, e isso derruba o setup da entry inteira. Ver o
    # comentario de `PANEL_URL_PATH`.
    await hass.http.async_register_static_paths(
        [StaticPathConfig(f"/{PANEL_URL_PATH}", frontend_dir, cache_headers=False)]
    )

    await panel_custom.async_register_panel(
        hass,
        webcomponent_name=WEBCOMPONENT_NAME,
        frontend_url_path=FRONTEND_URL_PATH,
        module_url=f"/{PANEL_URL_PATH}/{PANEL_JS}",
        sidebar_title="Koryx Remote",
        sidebar_icon=SIDEBAR_ICON,
        # `False` porque e um web component de verdade (Lit), nao um app em
        # React no iframe: sem iframe o painel compartilha o `hass` com o
        # resto da UI e o tema claro/escuro vale sozinho.
        embed_iframe=False,
        require_admin=False,
    )
    _LOGGER.debug("painel %s registrado em /%s", WEBCOMPONENT_NAME, FRONTEND_URL_PATH)


def async_unregister_panel(hass: HomeAssistant) -> None:
    """Remove o painel quando a ultima entry sai.

    Sem isto, desligar a integracao deixaria um item quebrado na sidebar:
    o HA mantem o registro do painel mesmo depois do unload da entry.
    """
    if not hass.data.pop(f"{DOMAIN}_panel_registered", None):
        return
    try:
        frontend.async_remove_panel(hass, FRONTEND_URL_PATH)
    except KeyError:
        # Ja nao estava registrado (outro caminho removeu antes). Nao e erro:
        # o objetivo — nao sobrar item orfao — esta cumprido.
        pass


async def async_setup_panel(hass: HomeAssistant) -> None:
    """Ponto de entrada usado pelo `async_setup_entry`."""
    await async_register_panel(hass)


__all__: list[str] = [
    "async_register_panel",
    "async_unregister_panel",
    "async_setup_panel",
    "FRONTEND_URL_PATH",
    "PANEL_URL_PATH",
    "WEBCOMPONENT_NAME",
]
