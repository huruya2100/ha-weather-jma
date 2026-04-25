"""Button platform for ha-weather-jma."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import async_generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import BUTTON_FORCE_REFRESH, DOMAIN, ENTITY_GROUP_MANAGEMENT
from .entity import HaWeatherJmaBaseEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the button platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    if ENTITY_GROUP_MANAGEMENT not in coordinator.location.enabled_entity_groups:
        return

    entity = HaWeatherJmaForceRefreshButtonEntity(coordinator)
    entity.entity_id = async_generate_entity_id(
        "button.{}",
        f"ha_weather_jma_{coordinator.location.entry_slug}_{BUTTON_FORCE_REFRESH}",
        hass=hass,
    )
    async_add_entities([entity])


class HaWeatherJmaForceRefreshButtonEntity(HaWeatherJmaBaseEntity, ButtonEntity):
    """Button entity that triggers an immediate refresh."""

    entity_description = ButtonEntityDescription(
        key=BUTTON_FORCE_REFRESH,
        translation_key=BUTTON_FORCE_REFRESH,
    )

    def __init__(self, coordinator) -> None:
        super().__init__(
            coordinator,
            f"ha_weather_jma_{coordinator.location.entry_id}_{BUTTON_FORCE_REFRESH}",
        )
        self._attr_translation_key = BUTTON_FORCE_REFRESH

    async def async_press(self) -> None:
        """Trigger an immediate refresh."""
        await self.coordinator.async_request_refresh()
