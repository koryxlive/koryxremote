"""Login da conta Koryx Remote dentro do Home Assistant."""

from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_PASSWORD
from homeassistant.helpers import selector
from homeassistant.helpers.selector import (
    EntityFilterSelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_ALEXA_USER_ID,
    CONF_API_URL,
    CONF_CREDENTIAL,
    CONF_EMAIL,
    CONF_ENDS_AT,
    CONF_EXPOSED_ENTITIES,
    CONF_PAIR_CODE,
    CONF_PLAN,
    CONF_RELAY_URL,
    CONF_REPORT_STATE,
    CONF_SLUG,
    CONF_URL,
    DEFAULT_API_URL,
    DOMAIN,
    EXPOSABLE_DOMAINS,
)
from .version import async_integration_version


class KoryxRemoteConfigFlow(ConfigFlow, domain=DOMAIN):
    """Um e-mail, uma senha, e a casa fica ligada."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Entrega a tela de escolha das entidades expostas à Alexa."""
        return KoryxRemoteOptionsFlow()

    def __init__(self) -> None:
        self._email = ""
        self._password = ""
        self._pair_code = ""
        self._api_url = ""
        self._credential = ""
        self._relay_url = ""
        self._slug = ""
        self._url = ""
        self._plan = "trial"
        self._ends_at = ""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Menu de entrada: login por e-mail (1ª casa) ou código de pareamento.

        A 1ª casa continua no login por e-mail, com zero fricção. As demais são
        criadas no painel web, que entrega um código — o HA digita o código e
        liga a casa certa, sem ambiguidade entre "casa nova" e "religar a mesma".
        """
        return self.async_show_menu(step_id="user", menu_options=["login", "pair"])

    async def async_step_login(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._email = str(user_input[CONF_EMAIL]).strip().lower()
            self._password = str(user_input[CONF_PASSWORD])
            await self.async_set_unique_id(self._email)
            self._abort_if_unique_id_configured()
            return await self._link_or_ask_server(DEFAULT_API_URL)
        return self.async_show_form(step_id="login", data_schema=self._user_schema())

    async def async_step_pair(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._pair_code = str(user_input[CONF_PAIR_CODE]).strip().upper()
            try:
                paired = await _pair(
                    DEFAULT_API_URL,
                    self._pair_code,
                    await async_integration_version(self.hass),
                )
            except InvalidCode:
                return self.async_show_form(
                    step_id="pair",
                    data_schema=self._pair_schema(),
                    errors={"base": "invalid_code"},
                )
            except (aiohttp.ClientError, TimeoutError, KeyError):
                return self.async_show_form(
                    step_id="pair",
                    data_schema=self._pair_schema(),
                    errors={"base": "cannot_connect"},
                )
            self._api_url = DEFAULT_API_URL
            self._credential = str(paired["credential"])
            self._relay_url = str(paired["relayUrl"])
            self._slug = str(paired["slug"])
            self._url = str(paired["url"])
            self._plan = str(paired.get("plan") or "trial")
            self._ends_at = str(paired.get("endsAt") or "")
            # Um id por casa: o mesmo e-mail pode ter várias casas, então o
            # `unique_id` não pode ser o e-mail aqui (senão só uma entry).
            await self.async_set_unique_id(f"installation-{str(paired['installationId'])}")
            self._abort_if_unique_id_configured()
            return await self.async_step_linked()
        return self.async_show_form(step_id="pair", data_schema=self._pair_schema())

    async def async_step_server(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return await self._link_or_ask_server(str(user_input[CONF_API_URL]).rstrip("/"), from_server=True)
        return self.async_show_form(step_id="server", data_schema=self._server_schema())

    async def _link_or_ask_server(self, api_url: str, *, from_server: bool = False) -> ConfigFlowResult:
        try:
            linked = await _link(
                api_url,
                self._email,
                self._password,
                # Fora do loop: `_link` roda no event loop e ler o manifest
                # de forma sincrona aqui seria bloqueante (aviso do HA).
                await async_integration_version(self.hass),
            )
        except InvalidAuth:
            return self.async_show_form(
                step_id="login",
                data_schema=self._user_schema(),
                errors={"base": "invalid_auth"},
            )
        except AccessEnded:
            return self.async_show_form(
                step_id="login",
                data_schema=self._user_schema(),
                errors={"base": "access_ended"},
            )
        except (aiohttp.ClientError, TimeoutError, KeyError):
            if not from_server:
                return await self.async_step_server()
            return self.async_show_form(
                step_id="server",
                data_schema=self._server_schema(),
                errors={"base": "cannot_connect"},
            )
        self._password = ""
        self._api_url = api_url
        self._credential = str(linked["credential"])
        self._relay_url = str(linked["relayUrl"])
        self._slug = str(linked["slug"])
        self._url = str(linked["url"])
        self._plan = str(linked.get("plan") or "trial")
        self._ends_at = str(linked.get("endsAt") or "")
        return await self.async_step_linked()

    async def async_step_linked(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Tela final: mostra o endereço antes de fechar.

        Sem isso a pessoa termina o login sem saber qual endereço abrir de
        fora — o `external_url` até fica gravado no HA, mas não aparece na
        hora em que ela precisa.
        """
        if user_input is not None:
            return self.async_create_entry(
                title=str(self._url),
                data={
                    CONF_API_URL: self._api_url,
                    CONF_EMAIL: self._email,
                    CONF_CREDENTIAL: self._credential,
                    CONF_RELAY_URL: self._relay_url,
                    CONF_SLUG: self._slug,
                    CONF_URL: self._url,
                    # Plano e fim do acesso ficam gravados: o sensor de
                    # vencimento já nasce com a data, mesmo antes do 1º PING.
                    CONF_PLAN: self._plan,
                    CONF_ENDS_AT: self._ends_at,
                },
            )
        return self.async_show_form(
            step_id="linked",
            description_placeholders={"url": str(self._url)},
            data_schema=vol.Schema({}),
        )

    def _user_schema(self) -> vol.Schema:
        email = (
            vol.Required(CONF_EMAIL, default=self._email)
            if self._email
            else vol.Required(CONF_EMAIL)
        )
        return vol.Schema(
            {
                email: TextSelector(TextSelectorConfig(type=TextSelectorType.EMAIL)),
                vol.Required(CONF_PASSWORD): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
            }
        )

    def _server_schema(self) -> vol.Schema:
        return vol.Schema({vol.Required(CONF_API_URL, default=DEFAULT_API_URL): str})

    def _pair_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_PAIR_CODE, default=self._pair_code): str,
            }
        )


class KoryxRemoteOptionsFlow(OptionsFlow):
    """Escolha das entidades que a Alexa enxerga, e o Report State.

    O seletor de entidades do HA (`EntitySelector`) já entrega busca, nome
    amigável e seleção múltipla — a lista vem do registry, não de texto
    digitado. Isso evita o problema do AMP/MAHM, onde errar o nome exato do
    dispositivo faz ele sumir sem aviso.

    O que ele **não** faz: um filtro por domínio em forma de chips clicáveis.
    O `filter` do HA só *restringe* a lista (aos `EXPOSABLE_DOMAINS`) — não
    desenha abas. Testado na 0.2.16: `filter` como lista de configs por domínio
    não muda a UI; continua a lista única. Então quem procura usa a **busca**,
    que é nativa e suficiente com a lista já limitada aos domínios expostos.

    O `reorder=True` é o ganho real: mantém a ordem de seleção estável entre
    aberturas, o que importa numa lista que pode passar de uma centena.

    O escopo (quais domínios aparecem) vem de `EXPOSABLE_DOMAINS`, em
    `const.py` — não é decidido aqui. Cada domínio a mais **não** exige
    mapeamento de capacidades nesta classe: quem serializa as interfaces da
    Alexa é o `ENTITY_ADAPTERS` do core, por domínio (`cover` → `SetPosition`,
    `climate` → `SetTargetTemperature`), e a integração só encaminha.
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            escolhidas = user_input.get(CONF_EXPOSED_ENTITIES) or []
            return self.async_create_entry(
                data={
                    CONF_EXPOSED_ENTITIES: list(escolhidas),
                    # O selector booleano sempre envia a chave; `False` aqui é
                    # "desmarcado de propósito", não ausência. Sem o `in`,
                    # um payload sem a chave viraria desmarcado silencioso.
                    CONF_REPORT_STATE: (
                        bool(user_input[CONF_REPORT_STATE])
                        if CONF_REPORT_STATE in user_input
                        else bool(self.config_entry.options.get(CONF_REPORT_STATE, True))
                    ),
                    # `async_create_entry` substitui TODO o options: sem
                    # repassar o id do usuário de sistema, salvar esta tela o
                    # apagaria e a integração criaria outro na próxima directive.
                    CONF_ALEXA_USER_ID: self.config_entry.options.get(CONF_ALEXA_USER_ID),
                }
            )

        atuais = self.config_entry.options.get(CONF_EXPOSED_ENTITIES) or []
        # Default `True` para acompanhar o padrão da integração: a caixa já
        # aparece marcada em quem nunca mexeu na opção.
        report_state = bool(self.config_entry.options.get(CONF_REPORT_STATE, True))
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_EXPOSED_ENTITIES, default=list(atuais)): EntitySelector(
                        EntitySelectorConfig(
                            # `domain` vai dentro de `filter`: no topo ele é o
                            # parâmetro legado, mantido só por compatibilidade.
                            #
                            # Isto **restringe** a lista aos `EXPOSABLE_DOMAINS`;
                            # não desenha um filtro clicável. Verificado na tela
                            # real (print do usuário, HA 2026.10.1): o core
                            # desenha o botão "Adicionar entidade" + uma busca
                            # com a lista de resultados. O fluxo é **um a um** —
                            # escolher, adicionar, repetir. Não há como marcar
                            # vários na lista e confirmar de uma vez: isso é
                            # estrutural do `ha-entities-picker`, não uma opção
                            # que falte configurar aqui.
                            #
                            # Quem tem 100+ dispositivos usa o painel da sidebar
                            # (`frontend/koryx-remote-panel.js`), que lista tudo
                            # com checkbox, filtra por domínio e salva de uma vez
                            # — na mesma `entry.options["exposed_entities"]`.
                            filter=EntityFilterSelectorConfig(domain=list(EXPOSABLE_DOMAINS)),
                            multiple=True,
                            # Preserva a ordem de seleção. Sem isto, reabrir a
                            # tela pode reordenar as entidades já escolhidas
                            # pelo critério do frontend, e uma lista de 100+
                            # itens que muda de lugar a cada visita parece
                            # instável.
                            reorder=True,
                        )
                    ),
                    # Selector booleano, não `bool` cru: um campo `bool` puro
                    # não renderiza o `data_description` nem resolve o rótulo
                    # de forma confiável no frontend — o campo aparece com a
                    # chave crua ("report_state"). Ver
                    # home-assistant/frontend#14164.
                    vol.Optional(CONF_REPORT_STATE, default=report_state): selector.selector(
                        {"boolean": {}}
                    ),
                }
            ),
        )


class InvalidAuth(Exception):
    """Conta recusada."""


class AccessEnded(Exception):
    """O acesso terminou: trial vencido ou plano pago sem renovação."""


class InvalidCode(Exception):
    """Código de pareamento inválido, usado ou expirado."""


async def _pair(api_url: str, code: str, version: str) -> dict[str, Any]:
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session, session.post(
        f"{api_url}/api/v1/agents/pair",
        json={"code": code, "version": version},
    ) as response:
        if response.status == 401:
            raise InvalidCode
        if response.status != 201:
            raise aiohttp.ClientError
        body = await response.json()
    if not isinstance(body, dict):
        raise KeyError
    return body


async def _link(api_url: str, email: str, password: str, version: str) -> dict[str, Any]:
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session, session.post(
        f"{api_url}/api/v1/agents/link",
        json={"email": email, "password": password, "version": version},
    ) as response:
        if response.status == 401:
            raise InvalidAuth
        if response.status == 403:
            raise AccessEnded
        if response.status != 201:
            raise aiohttp.ClientError
        body = await response.json()
    if not isinstance(body, dict):
        raise KeyError
    return body
