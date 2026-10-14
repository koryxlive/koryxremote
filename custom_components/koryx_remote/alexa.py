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
    import direto quebraria a integração numa refatoração do core.

    **Duck typing aqui não avisa quando falta um pedaço.** O core chama estes
    membros sem checar existência, em pontos diferentes, e cada ausência tem um
    sintoma próprio e silencioso:

    - `entity_config` — falta derruba **toda** entidade no `async_get_entities`
      (o `AlexaEntity` lê no construtor), e o `Discover` volta vazio mesmo com
      as luzes certas expostas.
    - `generate_alexa_id` — falta quebra a serialização de cada endpoint.
    - `supports_auth` / `should_report_state` — faltam no `AcceptGrant`; com
      `False` o handler pula o bloco de token, que é o que queremos.
    - `should_expose` — a única decisão de produto de verdade (ver abaixo).

    A lista dos membros que o core consulta sai de `grep -oE "config\\.[a-z_]+"`
    em `alexa/entities.py`, `alexa/handlers.py` e `alexa/smart_home.py`. Vale
    conferir contra o core antes de considerar o contrato fechado: um membro
    novo no core não dá erro de import, dá `AttributeError` em runtime que o
    `async_get_entities` engole.
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
    def entity_config(self) -> dict[str, Any]:
        """Personalização por entidade, que aqui não existe.

        O `AlexaEntity` do core lê `config.entity_config` no **construtor**, para
        cada entidade suportada, antes mesmo de perguntar se ela deve ser
        exposta. O `AbstractConfig` do core traz este default `{}`; como não
        herdamos dele, sem esta propriedade **todo** adapter estoura com
        `AttributeError: 'KoryxAlexaConfig' object has no attribute
        'entity_config'`, o `async_get_entities` engole a exceção e o
        `Discover` devolve `endpoints: []` com as luzes certas e expostas.

        Vazio é a resposta correta, não um placeholder: o mapa serve para o
        usuário renomear ou fixar `display_categories` por entidade no
        `configuration.yaml`, e a nossa seleção vive em `entry.options`. Quem
        quiser personalizar tem o HA para isso; a Alexa lê o nome do registry.
        """
        return {}

    @callback
    def generate_alexa_id(self, entity_id: str) -> str:
        """Id estável do endpoint na Alexa, derivado do `entity_id`.

        É o que o `Discover` publica como `endpointId` e o que a Alexa devolve
        em toda diretiva de execução. Tem de ser **estável entre descobertas**:
        se mudar, a Alexa perde a referência da luz e o usuário tem de redescobrir
        e reconfigurar o ambiente.

        O core faz `entity_id.replace(".", "#")`, que é o mesmo algoritmo aqui —
        e é por isso que não vale inventar outro (UUID, hash): o formato é
        observável pela Alexa e já é o que o HA usa em todo lugar.
        """
        return entity_id.replace(".", "#")

    @property
    def supports_auth(self) -> bool:
        """Sem OAuth própria: o vínculo é feito pela API, no Account Linking.

        O `AcceptGrant` do core consulta isto para decidir se guarda o código do
        grant. Devolver `True` faria o HA tentar um fluxo de token que não
        existe aqui, e a Alexa ficaria com um vínculo que o HA não reconhece.
        """
        return False

    @property
    def should_report_state(self) -> bool:
        """Sem Report State proativo, por enquanto.

        A Alexa só sabe o estado de uma luz quando pergunta. Se a luz mudar no
        interruptor da parede, o app da Alexa fica desatualizado até a próxima
        consulta. Ligar isso exige um `endpoint` de event gateway e token do
        LWA (a Alexa exige auth para receber eventos) — peça à parte, que não
        bloqueia o controle por voz.

        O core só entra no modo proativo com `supports_auth` **e** isto em
        `True`; como os dois são `False`, não há tentativa de conectar.
        """
        return False

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
