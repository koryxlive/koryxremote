"""Koryx Remote no Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .client import KoryxLink
from .const import CONF_URL, DOMAIN

PLATFORMS = ["binary_sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    public_url = entry.data.get(CONF_URL)
    if isinstance(public_url, str) and public_url.startswith("https://"):
        hass.config.async_update(external_url=public_url)
    link = KoryxLink(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = link
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    task = hass.async_create_task(link.run())

    def _unload() -> None:
        task.cancel()
        hass.async_create_task(link.async_stop())

    entry.async_on_unload(_unload)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unloaded
