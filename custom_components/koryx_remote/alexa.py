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

from .const import CONF_ALEXA_USER_ID, CONF_API_URL, CONF_CREDENTIAL, CONF_EXPOSED_ENTITIES, CONF_REPORT_STATE

_LOGGER = logging.getLogger(__name__)

# Pontuação que a Alexa não aceita em id de endpoint. Cópia da
# `TRANSLATION_TABLE` do `alexa/entities.py` do core: o `endpointId` que
# publicamos tem de ser idêntico ao que o HA geraria, senão a referência que a
# Alexa guardou não casa com a que o core monta ao executar o directive.
_ALEXA_ID_TRANSLATION = dict.fromkeys(map(ord, r"}{\/|\"()[]+~!><*%"), None)


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
        # Report State proativo: desligado por padrão. Gera tráfego a cada
        # mudança de estado reportável, então é opt-in — não imposto a toda
        # instalação. Ver `docs/report-state.md`.
        self._report_state = bool(entry.options.get(CONF_REPORT_STATE))

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
        self._report_state = bool(self.entry.options.get(CONF_REPORT_STATE))

    @property
    def endpoint(self) -> str | None:
        """Para onde o core manda os eventos proativos (Report State).

        Não é o event gateway da Amazon: o HA posta aqui, na API do Koryx, que
        repõe o token da LWA (que o HA nunca vê) e encaminha para
        `api.amazonalexa.com`. Assim o `client_secret` da Amazon não precisa
        existir dentro de casa, e a casa (atrás de NAT) não precisa de saída
        para a Amazon. Ver `docs/report-state.md`.

        Vazio quando o report state não está ligado: o core lê este valor no
        `set_authorized`, e `None` mantém o modo proativo desligado — que é o
        estado de quem não optou por ele.
        """
        if not self._report_state:
            return None
        api_url = self.entry.data.get(CONF_API_URL)
        if not isinstance(api_url, str) or not api_url:
            return None
        return f"{api_url.rstrip('/')}/api/v1/alexa/events"

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

        Mesmo algoritmo do core: `replace(".", "#")` e depois a `TRANSLATION_TABLE`,
        que apaga a pontuação que a Alexa não aceita em id (`/ \\ " ( ) [ ] + ~ !
        > < * %`). Sem a segunda parte, uma luz como `light.teto_(sala)` geraria
        um id diferente do que o HA usa, e a referência não bateria.
        """
        return entity_id.replace(".", "#").translate(_ALEXA_ID_TRANSLATION)

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
        """Report State proativo, quando o usuário liga e há casa vinculada.

        Com isto em `True`, o core registra um listener de mudança de estado e
        posta um `ChangeReport` em `endpoint` a cada mudança de entidade
        exposta — é o que faz a Alexa refletir uma luz que mudou na parede.

        `supports_auth` continua `False` de propósito: o vínculo OAuth é feito
        pela API no Account Linking, e o HA não participa dele. São coisas
        separadas — `should_report_state` é "eu quero avisar", `supports_auth`
        é "eu faço o fluxo de autorização". Aqui só o primeiro é verdadeiro.
        """
        return self._report_state

    @property
    def locale(self) -> str | None:
        """Locale da Alexa. **Não é cosmético: filtra quais capabilities são anunciadas.**

        O `serialize_discovery` do core faz `if locale not in i.supported_locales:
        continue` para **cada** interface antes de serializá-la. As capabilities
        declaram locales concretos (`en-US`, `pt-BR`, …) e **nenhuma** contém
        `None` — então devolver `None` (o default do `AbstractConfig`) descarta
        todas elas e o `Discover` publica a luz com `capabilities: []`. O
        resultado é cruel: a Alexa lista o dispositivo e diz que não sabe
        controlá-lo; nada aponta para cá, porque o Discovery "funcionou".

        `pt-BR` porque o HA desta integração é de casa brasileira e está no
        conjunto suportado do core. A Alexa aceita o locale do dispositivo e a
        Alexa API usa `pt-BR` para português do Brasil — devolver `en-US` também
        funcionaria e anunciaria as mesmas capabilities, mas respostas e nomes
        de rotina ficariam em inglês.
        """
        return "pt-BR"

    @callback
    def user_identifier(self) -> str:
        """Identifica o usuário nas chamadas de serviço.

        O `entity_id` da entry é estável e não carrega e-mail — o contexto dos
        serviços aparece em log e automação, e não é lugar para dado pessoal.
        """
        return self.entry.entry_id

    @callback
    def async_invalidate_access_token(self) -> None:
        """O core pede um token novo depois de um 401 no envio de evento.

        O token que devolvemos é a credencial do agente, que não expira e não
        muda. Não há nada a invalidar: se a API recusou (401), foi credencial
        revogada — só um novo vínculo resolve. Deixar como no-op evita que o
        core fique tentando em loop com a mesma credencial.
        """
        return

    async def async_get_access_token(self) -> str:
        """A credencial do agente, que assina o POST de eventos para a API.

        O core põe isto no `Authorization: Bearer` do POST para `endpoint`.
        **Não é o token da LWA**: é a mesma credencial `kr_...` que o HA já usa
        no WebSocket do Relay. A API valida pelo hash e, em nome da conta, repõe
        o token real da Amazon antes de encaminhar — então o segredo da LWA
        nunca chega ao HA.
        """
        return str(self.entry.data[CONF_CREDENTIAL])

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


async def _async_system_user_id(
    hass: HomeAssistant, entry: ConfigEntry
) -> str | None:
    """Id do usuário de sistema que assina as ações vindas da Alexa.

    **O contexto precisa de um usuário real do HA, não de um id qualquer.**
    O `Context.user_id` diz *quem* iniciou a mudança de estado, e o HA usa isso
    para decidir se aquela mudança é permitida (ver a doc do Context: "The
    user_id is used for restricting the ability to change the state of your
    home"). Um `user_id` que não corresponde a um usuário existente **não dá
    erro**: o `light.turn_on` chega a ser chamado, o HA descarta a alteração e
    a resposta ainda volta como `Alexa.Response` — o sintoma é a Alexa importar
    a luz e não conseguir controlá-la.

    Foi exatamente o que aconteceu aqui: passávamos `entry.entry_id`, que não é
    um usuário — um id que não corresponde a ninguém **não dá erro**: o
    `light.turn_on` chega a ser chamado e o HA descarta a alteração. Toda luz
    obedecia sem contexto e ignorava com contexto.

    O Home Assistant Cloud resolve do mesmo jeito (`cloud/prefs.py`):
    `async_create_system_user(..., group_ids=[GROUP_ID_ADMIN], local_only=True)`.
    É esse usuário que assina as ações da Alexa/Google, e é ele que reaproveitamos
    aqui — um único usuário para toda a instalação.

    O id fica em `entry.options` depois de criado: sem isso, cada reload da
    integração criaria mais um usuário "Koryx Remote" na tela de usuários.
    """
    from homeassistant.auth.const import GROUP_ID_ADMIN

    cached = entry.options.get(CONF_ALEXA_USER_ID)
    if isinstance(cached, str):
        user = await hass.auth.async_get_user(cached)
        # O usuário pode ter sido removido à mão; nesse caso criamos outro.
        if user is not None and user.is_active:
            return user.id

    try:
        user = await hass.auth.async_create_system_user(
            "Koryx Remote",
            group_ids=[GROUP_ID_ADMIN],
            local_only=True,
        )
    except Exception:  # pragma: no cover - só em HA sem auth
        _LOGGER.exception("Não consegui criar o usuário de sistema da Alexa")
        return None

    hass.config_entries.async_update_entry(
        entry,
        options={**entry.options, CONF_ALEXA_USER_ID: user.id},
    )
    return user.id


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
    user_id = await _async_system_user_id(hass, entry)
    return await smart_home.async_handle_message(
        hass,
        config,  # type: ignore[arg-type]
        {"directive": directive},
        context=Context(user_id=user_id),
    )
