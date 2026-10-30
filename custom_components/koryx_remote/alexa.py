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
from homeassistant.core import CALLBACK_TYPE

from .const import (
    CONF_ALEXA_USER_ID,
    CONF_API_URL,
    CONF_CREDENTIAL,
    CONF_EXPOSED_ENTITIES,
    CONF_REPORT_STATE,
    COVER_DEFAULT_DISPLAY_CATEGORY,
    COVER_DISPLAY_CATEGORIES,
)

_LOGGER = logging.getLogger(__name__)

# Pontuação que a Alexa não aceita em id de endpoint. Cópia da
# `TRANSLATION_TABLE` do `alexa/entities.py` do core: o `endpointId` que
# publicamos tem de ser idêntico ao que o HA geraria, senão a referência que a
# Alexa guardou não casa com a que o core monta ao executar o directive.
_ALEXA_ID_TRANSLATION = dict.fromkeys(map(ord, r"}{\/|\"()[]+~!><*%"), None)


def _install_cover_power_override() -> None:
    """Faz o `powerState` de uma cortina fechada valer `OFF`, não `ON`.

    **O bug.** O `AlexaPowerController` do core deriva `powerState` no ramo
    genérico como `self.entity.state != STATE_OFF`. Para `cover`, os estados são
    `open`/`closed`/`opening`/`closing` — **nenhum** é `off` — então `closed`
    cai em `is_on = True` e o core reporta `powerState = "ON"` com a cortina
    100% fechada. É o que o usuário vê: fecha a cortina, o HA reflete, e o app
    da Alexa continua com o toggle "Ativado".

    Pior que o valor errado é não haver evento. Entre `open` e `closed` o
    `powerState` não muda (ON nos dois) e a lista de propriedades serializadas
    fica idêntica, então o gate de "significância" do `state_report` descarta a
    transição e **nenhum** `ChangeReport` sai — a Alexa fica presa no último
    estado que conhecia.

    **Por que não usar o `should_expose`.** Seria a alavanca mais óbvia (a
    decisão de visibilidade é nossa), mas ela é o filtro tanto do `Discover`
    **quanto** do Report State: esconder a entidade fechada faz o listener
    descartá-la antes de montar o `ChangeReport`, e a Alexa nunca fica sabendo
    do OFF. Não dá para injetar estado por ali.

    **O que fazemos.** O `ENTITY_ADAPTERS` do core é um `Registry` — um `dict`
    simples (`homeassistant.util.decorator`) — e a chave de um domínio pode ser
    trocada. Registramos um `CoverCapabilities` subclassado que troca **só** a
    interface de energia; `rangeValue`, categoria, `PlaybackController` e
    `EndpointHealth` continuam os do core.

    **O que muda.** Só o `powerState`: `closed` → `OFF`; qualquer outro estado
    (`open`, `opening`, `closing`) → `ON`, como antes. Como o valor passa a
    mudar de verdade entre aberta e fechada, a transição volta a ser
    significativa e o `ChangeReport` sai.

    Idempotente: reexecutar só reatribui a mesma chave num dict (dois setups,
    um reload). Não guarda estado global.
    """
    from homeassistant.components import cover
    from homeassistant.components.alexa import capabilities, entities
    from homeassistant.const import STATE_OFF, EntityStateAttribute

    class _KoryxPowerController(capabilities.AlexaPowerController):
        """`AlexaPowerController` que entende o vocabulário de `cover`.

        Só o ramo de `cover` é diferente; o resto (`climate`, `fan`, …) fica no
        `super()`, para não reimplementar o que o core já acerta.
        """

        def get_property(self, name: str) -> Any:
            if name != "powerState":
                return super().get_property(name)
            # `closed` é o "desligado" da cortina. `STATE_OFF` entra junto por
            # simetria: o core já trata `cover.state == "off"` como fechado.
            if self.entity.state in (STATE_OFF, "closed"):
                return "OFF"
            return "ON"

    class _KoryxCoverCapabilities(entities.CoverCapabilities):
        """`CoverCapabilities` com o `powerState` corrigido.

        `interfaces()` é o do core, copiado porque o gen é construído lá e não
        há hook para trocar uma interface só. A única diferença é o
        `AlexaPowerController` — as demais linhas são idênticas, para o
        mapeamento de capacidade continuar sendo o do core.
        """

        def interfaces(self):
            device_class = self.entity.attributes.get(EntityStateAttribute.DEVICE_CLASS)
            if device_class not in (
                cover.CoverDeviceClass.GARAGE,
                cover.CoverDeviceClass.GATE,
            ):
                yield _KoryxPowerController(self.entity)

            supported = self.entity.attributes.get(
                EntityStateAttribute.SUPPORTED_FEATURES, 0
            )
            if supported & cover.CoverEntityFeature.SET_POSITION:
                yield capabilities.AlexaRangeController(
                    self.entity, instance=f"{cover.DOMAIN}.{cover.ATTR_POSITION}"
                )
            elif supported & (
                cover.CoverEntityFeature.CLOSE | cover.CoverEntityFeature.OPEN
            ):
                yield capabilities.AlexaModeController(
                    self.entity, instance=f"{cover.DOMAIN}.{cover.ATTR_POSITION}"
                )
            if supported & cover.CoverEntityFeature.SET_TILT_POSITION:
                yield capabilities.AlexaRangeController(
                    self.entity, instance=f"{cover.DOMAIN}.tilt"
                )
            if supported & (
                cover.CoverEntityFeature.STOP | cover.CoverEntityFeature.STOP_TILT
            ):
                yield capabilities.AlexaPlaybackController(
                    self.entity, instance=f"{cover.DOMAIN}.stop"
                )
            yield capabilities.AlexaEndpointHealth(self.hass, self.entity)
            yield capabilities.Alexa(self.entity)

    entities.ENTITY_ADAPTERS["cover"] = _KoryxCoverCapabilities


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
        # Entidades que o usuário marcou na tela de Opções. O escopo (domínios
        # escolhíveis) vive em `EXPOSABLE_DOMAINS`, no `const.py`; aqui é só o
        # conjunto concreto. `should_expose` e a inferência de categoria
        # (`_build_entity_config`) leem daqui.
        self._exposed = set(entry.options.get(CONF_EXPOSED_ENTITIES) or [])
        # Report State proativo: **ligado por padrão**. O custo é baixo e só
        # existe quando a Alexa já autorizou a casa: o core só entra no modo
        # proativo depois de um `set_authorized(True)`, que acontece no
        # primeiro directive. Sem vínculo ativo, `should_report_state` é
        # verdadeiro mas nenhum listener é registrado — não há tráfego para
        # quem nunca usou a skill. O usuário pode desligar na tela de Opções.
        # Ver `docs/report-state.md`.
        self._report_state = bool(entry.options.get(CONF_REPORT_STATE, True))
        # Categoria por entidade (`entity_config`), montada sob demanda e
        # descartada no `refresh`. Ver `entity_config`.
        self._entity_config: dict[str, dict[str, Any]] | None = None

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
        self._report_state = bool(self.entry.options.get(CONF_REPORT_STATE, True))
        # O `entity_config` depende de quais entidades estão expostas; um
        # reload troca a seleção, então o cache tem de cair junto.
        self._entity_config = None

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
        """Categoria da Alexa por entidade, inferida — não configurada.

        O `AlexaEntity` do core lê `config.entity_config` no **construtor**, para
        cada entidade suportada, antes mesmo de perguntar se ela deve ser
        exposta. O `AbstractConfig` do core traz este default `{}`; como não
        herdamos dele, sem esta propriedade **todo** adapter estoura com
        `AttributeError: 'KoryxAlexaConfig' object has no attribute
        'entity_config'`, o `async_get_entities` engole a exceção e o
        `Discover` devolve `endpoints: []` com as luzes certas e expostas.

        **Por que não é `{}`.** O core deriva a categoria da Alexa da
        `device_class` da entidade, em `AlexaEntity.default_display_categories`
        — e para `cover` sem `device_class` a resposta é `OTHER` ("Outro" no
        app). A maioria das cortinas/persianas reais (MQTT, Tuya, HomeKit) não
        publica `device_class`, e pedir que cada usuário edite o HA de cada
        dispositivo é inviável: a Alexa precisa entender a cortina como cortina
        mesmo que o HA não tenha dito o que ela é.

        Então **inferimos só o que o core não sabe**: para `cover`, o
        `device_class` (quando existe) vira uma categoria de
        `COVER_DISPLAY_CATEGORIES`; quando falta, cai no
        `COVER_DEFAULT_DISPLAY_CATEGORY` (`INTERIOR_BLIND`, o rótulo que a
        Alexa usa para cortina/veneziana/persiana). Isso não sobrepõe o core:
        ele aplica este mapa antes do default, e o resultado é idêntico ao que
        o core produziria com `device_class` presente — só que agora também
        quando ele falta.

        **Só `cover` entra.** É o único domínio em que o core devolve `OTHER`
        por falta de dado (ver `default_display_categories` de cada adapter:
        `light`, `climate`, `lock`, `fan`… já têm categoria fixa). Os demais
        ficam fora para não mexer no que o core acerta — e para o mapa crescer
        só onde há ganho real.

        `CONF_DISPLAY_CATEGORIES` no `entity_config` também muda as interfaces
        anunciadas (`AlexaDoorbellEventSource`, sensores de contato/movimento),
        mas **apenas** para categorias de sensor — uma categoria de `cover`
        (`INTERIOR_BLIND` etc.) não dispara nenhum desses ramos, então injetar
        aqui não altera as capacidades, só o rótulo.

        Montado uma vez por config e cacheado: a property é consultada no
        construtor de **cada** entidade, e varrer `hass.states` a cada chamada
        seria O(n²) no `Discover`.
        """
        if self._entity_config is None:
            self._entity_config = self._build_entity_config()
        return self._entity_config

    def _build_entity_config(self) -> dict[str, dict[str, Any]]:
        """Categorias inferidas, só para as entidades cobertas pelo mapa.

        Só as `cover` expostas entram — o `entity_config` do core é lido no
        construtor de toda entidade suportada, mas devolver entrada para quem
        já tem categoria do core seria interferir sem motivo.
        """
        config: dict[str, dict[str, Any]] = {}
        for entity_id in self._exposed:
            if not entity_id.startswith("cover."):
                continue
            state = self.hass.states.get(entity_id)
            if state is None:
                continue
            # `device_class` é opcional em `cover`; `None` quando o
            # fabricante/descoberta não informa — o caso que queremos cobrir.
            device_class = state.attributes.get("device_class")
            category = COVER_DISPLAY_CATEGORIES.get(
                device_class, COVER_DEFAULT_DISPLAY_CATEGORY
            )
            config[entity_id] = {"display_categories": category}
        return config

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


def _normalize_range_instance(directive: dict[str, Any]) -> None:
    """Repõe o `instance` que a Alexa omite no `SetRangeValue` de range único.

    **O bug.** No app, o slider de percentual (cortina, ventilador, aspirador,
    umidificador) manda `Alexa.RangeController/SetRangeValue` com o
    `rangeValue` no payload, mas **sem** a chave `instance` no header. O
    `AlexaDirective.load_entity` do core só lê `instance` do *header*
    (`self._directive[API_HEADER]["instance"]`), então ela fica `None`; o
    `async_api_set_range` compara a instance com a string do domínio
    (`cover.position`, `fan.percentage`, `vacuum.fan_speed`,
    `humidifier.humidity`), não casa, cai no `else` e levanta
    `DIRECTIVE_NOT_SUPPORTED`. A Alexa mostra "não está respondendo", mesmo o
    `Discover` anunciando a capability certa.

    **Por que a Alexa omite.** A `instance` só é obrigatória quando o endpoint
    declara **mais de uma** interface daquele tipo (duas `RangeController`).
    Nestes domínios o core só publica **uma** `RangeController` por entidade,
    então a Alexa pode omitir — e cabe ao dispositivo resolver pelo contexto.
    O core não faz esse fallback.

    **O que fazemos.** Em `SetRangeValue` de `RangeController` **sem**
    `instance`, injetamos a instance default do domínio do endpoint. O mapa
    abaixo espelha o que o `interfaces()` do core anuncia e o que o handler
    compara. Qualquer outro caso — outra interface, domínio fora do mapa,
    `instance` já presente — passa intocado.

    Muta o `directive` in place; o `async_handle_directive` o recebe já fora do
    envelope e o re-embrulha logo em seguida, então a alteração segue junto.
    """
    header = directive.get("header")
    if not isinstance(header, dict):
        return
    if header.get("namespace") != "Alexa.RangeController":
        return
    if header.get("name") != "SetRangeValue":
        return
    if "instance" in header:
        return
    endpoint = directive.get("endpoint")
    if not isinstance(endpoint, dict):
        return
    endpoint_id = endpoint.get("endpointId")
    if not isinstance(endpoint_id, str):
        return
    entity_id = endpoint_id.replace("#", ".")
    domain = entity_id.split(".", 1)[0]

    if domain == "cover":
        from homeassistant.components import cover

        header["instance"] = f"{cover.DOMAIN}.{cover.ATTR_POSITION}"
    elif domain == "fan":
        from homeassistant.components import fan

        header["instance"] = f"{fan.DOMAIN}.{fan.ATTR_PERCENTAGE}"
    elif domain == "vacuum":
        from homeassistant.components import vacuum

        header["instance"] = f"{vacuum.DOMAIN}.{vacuum.ATTR_FAN_SPEED}"
    elif domain == "humidifier":
        from homeassistant.components import humidifier

        header["instance"] = f"{humidifier.DOMAIN}.{humidifier.ATTR_HUMIDITY}"


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

    # Antes de entregar ao core: repõe o `instance` que a Alexa omite no
    # `SetRangeValue` quando o endpoint só tem uma RangeController (cortina,
    # ventilador, aspirador). Sem isto o core recusa com `INVALID_DIRECTIVE`
    # e a Alexa mostra "não está respondendo". Ver `_normalize_range_instance`.
    _normalize_range_instance(directive)

    config = KoryxAlexaConfig(hass, entry)
    user_id = await _async_system_user_id(hass, entry)
    return await smart_home.async_handle_message(
        hass,
        config,  # type: ignore[arg-type]
        {"directive": directive},
        context=Context(user_id=user_id),
    )


async def async_enable_report_state(
    hass: HomeAssistant, entry: ConfigEntry
) -> CALLBACK_TYPE | None:
    """Liga o Report State proativo e devolve o unsubscriber.

    **Por que não basta `should_report_state = True`.** O handler do core para
    `Alexa.Authorization/AcceptGrant` só chama o `async_enable_proactive_mode`
    dentro de um `if config.supports_auth:`. A nossa `KoryxAlexaConfig` tem
    `supports_auth = False` de propósito — o vínculo OAuth é feito pela API, no
    Account Linking, e o HA não participa dele. O efeito colateral é que o
    caminho oficial de ligar o modo proativo nunca roda para nós, e o HA fica
    sem nenhum listener de `EVENT_STATE_CHANGED`.

    Sem listener, nenhum `ChangeReport` sai por mudança de estado. A Alexa só
    descobre o estado novo quando o usuário abre o app e ela faz uma consulta
    sob demanda — que é o "delay grande" que o usuário via: a luz apagava na
    parede e o app só atualizava muito depois.

    Chamamos a `async_enable_proactive_mode` direto aqui, no setup da
    integração, quando o usuário pediu para reportar estado. Ela é pública e
    autocontida: valida que dá para obter o token (`async_get_access_token`,
    que devolve a credencial do agente) e registra o listener. O retorno é o
    unsubscriber, que guardamos para desligar no unload.

    Import tardio pela mesma razão do `async_handle_directive`: não carregar o
    componente `alexa` inteiro para quem não usa.

    Devolve `None` quando o report state está desligado nas opções — nada a
    fazer, e o chamador não precisa saber disso.
    """
    if not bool(entry.options.get(CONF_REPORT_STATE, True)):
        return None

    from homeassistant.components.alexa import state_report

    config = KoryxAlexaConfig(hass, entry)
    return await state_report.async_enable_proactive_mode(hass, config)  # type: ignore[arg-type]
