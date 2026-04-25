"""ha-weather-jma integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HaWeatherJmaApiClient
from .const import DOMAIN
from .coordinator import HaWeatherJmaCoordinator
from .parser import build_location_config

PLATFORMS: tuple[Platform, ...] = (
    Platform.WEATHER,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ha-weather-jma from a config entry."""
    api_client = HaWeatherJmaApiClient(async_get_clientsession(hass))
    merged_data = {**entry.data, **entry.options}
    location = build_location_config(entry.entry_id, entry.title, merged_data)
    coordinator = HaWeatherJmaCoordinator(hass, api_client, location)

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry after options updates."""
    await hass.config_entries.async_reload(entry.entry_id)
