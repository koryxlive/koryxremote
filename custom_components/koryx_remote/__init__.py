"""Koryx Remote no Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .client import KoryxLink
from .const import CONF_URL, DOMAIN

PLATFORMS = ["binary_sensor", "sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    public_url = entry.data.get(CONF_URL)
    if isinstance(public_url, str) and public_url.startswith("https://"):
        # `async_update` é coroutine: sem o `await` ela nunca roda, a URL
        # externa não é gravada e o HA loga
        # "coroutine 'Config.async_update' was never awaited" a cada setup.
        await hass.config.async_update(external_url=public_url)
    link = KoryxLink(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = link
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    task = hass.async_create_task(link.run())

    def _unload() -> None:
        task.cancel()
        hass.async_create_task(link.async_stop())

    entry.async_on_unload(_unload)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Listener de `options`: o HA exige uma coroutine aqui, não uma função.

    O `KoryxAlexaConfig` lê a seleção do `entry.options` a cada directive, então
    não há cache para invalidar do lado da Alexa — só avisar a API de que a
    lista mudou.
    """
    link: KoryxLink | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if link is not None:
        await link.notify_entities_changed()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unloaded
