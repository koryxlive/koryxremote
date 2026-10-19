"""Descobre se há versão nova da integração e avisa uma vez.

O HACS é ruim de avisar: a entidade `update` dele às vezes atrasa ou some.
Aqui a fonte é a nossa: primeiro o GitHub do HACS (o mesmo repo do
`sync-integration.sh`), depois o `/ha/version` da API (mesmo `manifest` do
zip). Sem instalar automaticamente — só informar.

O push inicial é uma `persistent_notification` no HA (sino). Uma por versão
nova; se a casa já está atualizada, a notificação some.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import aiohttp
from awesomeversion import AwesomeVersion
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_API_URL,
    CONF_UPDATE_NOTIFIED,
    DEFAULT_API_URL,
    DOMAIN,
    GITHUB_MANIFEST_URL,
    UPDATE_CHECK_HOURS,
)
from .version import async_integration_version

_LOGGER = logging.getLogger(__name__)

# Id fixo da notificação: uma só no sino; o conteúdo muda com a versão.
_NOTIFICATION_ID = f"{DOMAIN}_update_available"


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    """O que as entidades e o push leem."""

    installed: str
    latest: str | None
    release_url: str | None
    available: bool


class KoryxUpdateCoordinator(DataUpdateCoordinator[UpdateInfo]):
    """Consulta periódica da versão publicada."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_update",
            update_interval=timedelta(hours=UPDATE_CHECK_HOURS),
            config_entry=entry,
        )
        self.entry = entry

    async def _async_update_data(self) -> UpdateInfo:
        installed = await async_integration_version(self.hass)
        # Falha de rede NÃO pode derrubar a entry: o túnel e o plano continuam
        # importando mais que o aviso de versão. Sem latest, as entidades
        # mostram só a instalada e tentam de novo no próximo intervalo.
        latest, release_url = await self._async_fetch_latest()
        available = bool(latest) and _is_newer(latest, installed)
        info = UpdateInfo(
            installed=installed,
            latest=latest,
            release_url=release_url,
            available=available,
        )
        await self._async_sync_notification(info)
        return info

    async def _async_fetch_latest(self) -> tuple[str | None, str | None]:
        """GitHub primeiro (espelha o HACS); API como fallback."""
        session = async_get_clientsession(self.hass)
        github = await self._async_from_github(session)
        if github[0]:
            return github
        return await self._async_from_api(session)

    async def _async_from_github(
        self, session: aiohttp.ClientSession
    ) -> tuple[str | None, str | None]:
        try:
            async with session.get(
                GITHUB_MANIFEST_URL,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status != 200:
                    _LOGGER.debug(
                        "GitHub manifest HTTP %s — tentando API", response.status
                    )
                    return None, None
                body: Any = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOGGER.debug("GitHub manifest indisponível: %s", err)
            return None, None
        version = _as_version(body.get("version") if isinstance(body, dict) else None)
        if not version:
            return None, None
        return version, f"https://github.com/koryxlive/koryxremote/releases/tag/v{version}"

    async def _async_from_api(
        self, session: aiohttp.ClientSession
    ) -> tuple[str | None, str | None]:
        api_url = str(self.entry.data.get(CONF_API_URL) or DEFAULT_API_URL).rstrip("/")
        url = f"{api_url}/ha/version"
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                if response.status != 200:
                    _LOGGER.debug("API /ha/version HTTP %s", response.status)
                    return None, None
                body: Any = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOGGER.debug("API /ha/version indisponível: %s", err)
            return None, None
        if not isinstance(body, dict):
            return None, None
        version = _as_version(body.get("version"))
        if not version:
            return None, None
        release = body.get("releaseUrl")
        release_url = release if isinstance(release, str) and release else (
            f"https://github.com/koryxlive/koryxremote/releases/tag/v{version}"
        )
        return version, release_url

    async def _async_sync_notification(self, info: UpdateInfo) -> None:
        """Push no sino: cria na primeira vez que a versão nova aparece."""
        from homeassistant.components import persistent_notification

        if not info.available or not info.latest:
            # Já atualizado (ou sem dado): tira o aviso velho do sino.
            persistent_notification.async_dismiss(self.hass, _NOTIFICATION_ID)
            return

        ja_avisou = self.entry.data.get(CONF_UPDATE_NOTIFIED)
        if ja_avisou == info.latest:
            return

        link = info.release_url or "https://github.com/koryxlive/koryxremote/releases"
        mensagem = (
            f"Koryx Remote **{info.latest}** está disponível "
            f"(você tem {info.installed}).\n\n"
            f"Atualize pelo **HACS** → Integrações → Koryx Remote e reinicie "
            f"o Home Assistant.\n\n"
            f"[Notas da versão]({link})"
        )
        persistent_notification.async_create(
            self.hass,
            mensagem,
            title="Atualização Koryx Remote",
            notification_id=_NOTIFICATION_ID,
        )
        # Persistir fora do caminho síncrono do refresh: `async_update_entry`
        # no meio do setup da entry pode recarregar a integração cedo demais.
        if self.entry.data.get(CONF_UPDATE_NOTIFIED) != info.latest:
            self.hass.async_create_task(self._async_remember_notified(info.latest))

    async def _async_remember_notified(self, version: str) -> None:
        """Grava a versão avisada para não repetir o push a cada poll/restart."""
        if self.entry.data.get(CONF_UPDATE_NOTIFIED) == version:
            return
        self.hass.config_entries.async_update_entry(
            self.entry,
            data={**self.entry.data, CONF_UPDATE_NOTIFIED: version},
        )


def _as_version(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    texto = value.strip().lstrip("vV")
    return texto or None


def _is_newer(latest: str, installed: str) -> bool:
    try:
        return AwesomeVersion(latest) > AwesomeVersion(installed)
    except Exception:  # noqa: BLE001 — versão malformada: compara texto
        return latest != installed
