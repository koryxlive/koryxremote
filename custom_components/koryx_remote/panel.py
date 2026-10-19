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

from .const import CUSTOM_ICON_PREFIX, DOMAIN
from .version import async_integration_version

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

# Modulo que registra o K da marca em `window.customIcons`. Fica separado do
# bundle do painel porque a sidebar desenha o icone ao carregar o HA, antes de
# o usuario navegar para `/koryx-remote`; carregar o painel inteiro so para
# isso seria pior (e o `panel_custom` so carrega o modulo na rota dele).
ICONS_JS = "koryx-icons.js"

# `webcomponent_name` precisa bater **exatamente** com o nome passado ao
# `customElements.define()` la no JS. Se divergir, o painel registra mas o
# frontend nao acha o elemento e a pagina fica em branco — sem erro obvio.
WEBCOMPONENT_NAME = "koryx-remote-panel"

# `frontend_url_path` e o que aparece na URL: `/koryx-remote`.
FRONTEND_URL_PATH = "koryx-remote"

# Icone da sidebar: a marca da Koryx, e nao um `mdi:`.
#
# O HA NUNCA aceita imagem aqui — `frontend.Panel.sidebar_icon` e uma string e
# a sidebar resolve com `<ha-icon>`. O caminho estavel e o registro de icones
# customizados do frontend: `koryx_remote:k` (ver `frontend/koryx-icons.js`).
# O prefixo precisa bater com o que aquele arquivo registra em
# `window.customIcons`; divergir deixa o item da sidebar SEM icone, sem erro.
#
# Historico: `mdi:amazon-alexa` saiu do MDI e o item aparecia vazio; foi trocado
# por `mdi:cast-audio`, que e generico e nao comunica a marca. O K cobre os dois.
SIDEBAR_ICON = f"{CUSTOM_ICON_PREFIX}:k"


async def async_register_frontend_icon(hass: HomeAssistant) -> None:
    """Injeta o modulo que registra o K em `window.customIcons`.

    Idempotente pelo mesmo motivo do painel (duas entries, dois registros). O
    marcador e separado do painel: o painel pode falhar (e o `__init__` engole)
    sem levar o icone junto, e vice-versa.

    `frontend.add_extra_js_url` e **sincrono** e exige a chave `DATA_EXTRA_MODULE_URL`
    ja criada no `hass.data` — ela nasce no setup do componente `frontend`, que a
    integracao declara em `dependencies`. Se o componente nao estiver de pe, o
    `KeyError` sobe e o `__init__` o registra como falha do painel, sem derrubar
    o tunel.
    """
    if hass.data.get(f"{DOMAIN}_icons_registered"):
        return
    hass.data[f"{DOMAIN}_icons_registered"] = True

    # Mesmo motivo do `?v=` do painel: a URL do modulo precisa mudar a cada
    # release, senao o service worker do HA serve o JS antigo indefinidamente.
    # `cache_headers=False` no registro estatico nao basta — a URL e que fica
    # presa no cache do navegador.
    versao = await async_integration_version(hass)
    URL_ICONES = f"/{PANEL_URL_PATH}/{ICONS_JS}?v={versao}"
    frontend.add_extra_js_url(hass, URL_ICONES)
    # Guardado para o unload remover a URL exata (com a versao): remover sem a
    # versao nao casaria e o modulo seguiria sendo carregado depois do unload.
    hass.data[f"{DOMAIN}_icons_url"] = URL_ICONES


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

    # **A versao entra na query string da URL do modulo.** Sem isto, a URL era
    # sempre `/koryx_remote-panel/koryx-remote-panel.js`: o navegador e o
    # service worker do HA (`sw-modern.js`) guardavam o bundle antigo e o
    # serviam indefinidamente, mesmo depois de publicar uma correcao. Foi
    # exatamente por isso que o `SyntaxError` da 0.2.22 continuou aparecendo
    # depois de a 0.2.22 e a 0.2.23 terem sido publicadas — a URL nunca mudava,
    # entao o cache nunca era invalidado. Com `?v=<versao>`, cada release muda
    # a URL e o navegador baixa o arquivo novo.
    #
    # O `async_register_static_paths` acima serve o caminho **sem** a query
    # (o aiohttp resolve pelo path, ignorando a query string), entao o mesmo
    # registro estatico continua valendo — e a URL sem versao tambem segue
    # respondendo, para nao quebrar quem tem a antiga em cache.
    #
    # `config_panel_domain=DOMAIN` faz o painel aparecer tambem como aba
    # dentro de Configuracoes -> Dispositivos e servicos -> Koryx Remote. E o
    # caminho suportado para painel de integracao e o mesmo que o `panel_custom`
    # do core usa quando chamado com esse argumento (`HA >= 2026.3`); em HA
    # mais antigo o argumento e ignorado, e o painel segue so na sidebar.
    await async_register_frontend_icon(hass)
    versao = await async_integration_version(hass)

    await panel_custom.async_register_panel(
        hass,
        webcomponent_name=WEBCOMPONENT_NAME,
        frontend_url_path=FRONTEND_URL_PATH,
        module_url=f"/{PANEL_URL_PATH}/{PANEL_JS}?v={versao}",
        sidebar_title="Koryx Remote",
        sidebar_icon=SIDEBAR_ICON,
        # `False` porque e um web component de verdade (Lit), nao um app em
        # React no iframe: sem iframe o painel compartilha o `hass` com o
        # resto da UI e o tema claro/escuro vale sozinho.
        embed_iframe=False,
        require_admin=False,
        config_panel_domain=DOMAIN,
    )
    _LOGGER.debug("painel %s registrado em /%s", WEBCOMPONENT_NAME, FRONTEND_URL_PATH)


def async_unregister_panel(hass: HomeAssistant) -> None:
    """Remove o painel quando a ultima entry sai.

    Sem isto, desligar a integracao deixaria um item quebrado na sidebar:
    o HA mantem o registro do painel mesmo depois do unload da entry.

    Tambem tira a URL do modulo do K de `extra_js_url`. Ela e injetada no HTML
    do HA a cada carregamento; deixar registrada faria o navegador buscar um
    arquivo de uma integracao desinstalada (`404` no console) e, pior, o
    icone continuaria "existindo" na sidebar para um painel removido.
    """
    url_icones = hass.data.pop(f"{DOMAIN}_icons_url", None)
    if url_icones is not None:
        try:
            frontend.remove_extra_js_url(hass, url_icones)
        except KeyError:
            # Nunca foi registrada (falha no setup do icone). Nao e erro.
            pass
    hass.data.pop(f"{DOMAIN}_icons_registered", None)

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
