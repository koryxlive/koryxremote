"""Login da conta Koryx Remote dentro do Home Assistant."""

from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .const import CONF_API_URL, CONF_CREDENTIAL, CONF_EMAIL, CONF_ENDS_AT, CONF_PLAN, CONF_RELAY_URL, CONF_SLUG, CONF_URL, DEFAULT_API_URL, DOMAIN


class KoryxRemoteConfigFlow(ConfigFlow, domain=DOMAIN):
    """Um e-mail, uma senha, e a casa fica ligada."""

    VERSION = 1

    def __init__(self) -> None:
        self._email = ""
        self._password = ""
        self._api_url = ""
        self._credential = ""
        self._relay_url = ""
        self._slug = ""
        self._url = ""
        self._plan = "trial"
        self._ends_at = ""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._email = str(user_input[CONF_EMAIL]).strip().lower()
            self._password = str(user_input[CONF_PASSWORD])
            await self.async_set_unique_id(self._email)
            self._abort_if_unique_id_configured()
            return await self._link_or_ask_server(DEFAULT_API_URL)
        return self.async_show_form(step_id="user", data_schema=self._user_schema())

    async def async_step_server(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return await self._link_or_ask_server(str(user_input[CONF_API_URL]).rstrip("/"), from_server=True)
        return self.async_show_form(step_id="server", data_schema=self._server_schema())

    async def _link_or_ask_server(self, api_url: str, *, from_server: bool = False) -> ConfigFlowResult:
        try:
            linked = await _link(api_url, self._email, self._password)
        except InvalidAuth:
            return self.async_show_form(
                step_id="user",
                data_schema=self._user_schema(),
                errors={"base": "invalid_auth"},
            )
        except AccessEnded:
            return self.async_show_form(
                step_id="user",
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


class InvalidAuth(Exception):
    """Conta recusada."""


class AccessEnded(Exception):
    """O acesso terminou: trial vencido ou plano pago sem renovação."""


async def _link(api_url: str, email: str, password: str) -> dict[str, Any]:
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session, session.post(
        f"{api_url}/api/v1/agents/link",
        json={"email": email, "password": password, "version": "0.1.0"},
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
