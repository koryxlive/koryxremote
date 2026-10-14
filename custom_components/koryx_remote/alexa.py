"""A ponte entre a Alexa e as entidades desta casa.

O desenho aqui é o mesmo do Home Assistant Cloud: o directive cru que a Alexa
manda chega pelo túnel e é entregue ao `async_handle_message` do core, que
reaproveita os handlers oficiais (`TurnOn` -> `homeassistant.turn_on`, brilho,
cor, tudo). A nuvem não decide nada e não guarda estado da casa — ela só
encaminha.

Reaproveitar o core, em vez de reescrever o mapeamento de capacidades, é o que
mantém isto pequeno: o `HANDLERS` da Alexa já cobre os domínios e responde no
formato v3 exato que ela espera. Nós só temos que responder três perguntas
("quais entidades?", "qual locale?", "qual endpoint de report state?") e deixar
o core fazer o resto.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry

from .const import CONF_EXPOSED_ENTITIES

_LOGGER = logging.getLogger(__name__)

DOMAIN = "koryx_remote"


class KoryxAlexaConfig:
    """O que o `alexa_smart_home` do core precisa saber sobre esta casa.

    Implementa o mesmo contrato do `AbstractConfig`, sem herdar dele: o
    `homeassistant.components.alexa.config` não é API pública estável, e um
    import direto quebraria a integração numa refatoração do core. O contrato
    usado aqui é pequeno e verificável — `endpoint`, `locale`,
    `user_identifier` e `should_expose` — e é exatamente o que
    `async_handle_message` consulta.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        # Só luzes, por enquanto: é o que a tela de Opções deixa escolher, e o
        # que o Discovery anuncia. Um domínio novo aqui precisa do mapeamento
        # correspondente no core, que já existe para `switch`/`cover` — basta
        # liberar na seleção quando houver uso.
        self._exposed = set(entry.options.get(CONF_EXPOSED_ENTITIES) or [])

    @callback
    def should_expose(self, entity_id: str) -> bool:
        """Diz se a entidade entra no Discovery.

        É a única decisão de produto que a integração toma: o resto o core
        resolve. Uma entidade que sumiu do HA continua marcada aqui, mas o
        `alexa_smart_home` só anuncia o que existe no registry — não precisa
        limpar a seleção.
        """
        return entity_id in self._exposed

    def refresh(self) -> None:
        """Recarrega a seleção depois de mudar na tela de Opções."""
        self._exposed = set(self.entry.options.get(CONF_EXPOSED_ENTITIES) or [])

    @property
    def endpoint(self) -> str | None:
        """Para onde o HA mandaria Report State, se um dia ligarmos.

        Vazio por enquanto. O `should_report_state` do core só liga com
        `supports_auth` e token de acesso, então não haverá tentativa de
        proactive report sem isto preenchido.
        """
        return None

    @property
    def locale(self) -> str | None:
        """Idioma das respostas. `None` deixa o core usar o padrão (inglês)."""
        return None

    @callback
    def user_identifier(self) -> str:
        """Identifica o usuário nas chamadas de serviço.

        O `entity_id` da entry é estável e não carrega e-mail — o contexto dos
        serviços aparece em log e automação, e não é lugar para dado pessoal.
        """
        return self.entry.entry_id

    @callback
    def async_invalidate_access_token(self) -> None:
        """Sem token próprio: a autenticação acontece no túnel, não aqui."""
        return

    async def async_get_access_token(self) -> str | None:
        """Sem token próprio — a Alexa nunca fala direto com esta casa."""
        return None

    async def async_accept_grant(self, code: str) -> str | None:
        """O grant é aceito pela API no Account Linking, não pelo HA."""
        return None

    async def set_authorized(self, authorized: bool) -> None:
        """No-op: autorização é decidida pela credencial do túnel.

        O core chama isto no início de cada mensagem. Deixar o default da
        classe base criaria um `Store` em disco para um estado que já é
        controlado a cada reconexão do túnel.
        """
        return


async def async_handle_directive(
    hass: HomeAssistant,
    entry: ConfigEntry,
    directive: dict[str, Any],
) -> dict[str, Any]:
    """Processa um directive cru da Alexa com os handlers do core.

    O `directive` aqui é o objeto de dentro do envelope, sem a chave
    `"directive"` — é o formato que o túnel carrega, para não repetir a mesma
    palavra em cada camada. O `async_handle_message` do core, porém, espera o
    envelope inteiro: ele faz `request[API_DIRECTIVE][API_HEADER]` logo na
    entrada, como se tivesse recebido o corpo HTTP cru da Alexa. Re-embrulhar
    aqui, na fronteira, é o que mantém as duas convenções sem vazar uma para
    dentro da outra.

    Import tardio de propósito: `homeassistant.components.alexa` puxa o
    componente `alexa` inteiro, e a integração não deve carregá-lo só para
    existir — quem não usa Alexa não paga por ele.

    Devolve a resposta no formato v3 que a Alexa espera. Erros inesperados
    viram uma resposta de erro do próprio core, com o traceback no log: melhor
    a Alexa dizer "não consegui" do que a integração derrubar o túnel.
    """
    from homeassistant.components.alexa import smart_home

    from homeassistant.core import Context

    config = KoryxAlexaConfig(hass, entry)
    return await smart_home.async_handle_message(
        hass,
        config,  # type: ignore[arg-type]
        {"directive": directive},
        context=Context(user_id=entry.entry_id),
    )
