"""Binary sensor platform for ha-weather-jma."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import async_generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, ENTITY_GROUP_WARNINGS, WARNING_ENTITY_TITLES
from .coordinator import HaWeatherJmaCoordinator
from .entity import HaWeatherJmaBaseEntity
from .parser import warning_entity_title


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    if ENTITY_GROUP_WARNINGS not in coordinator.location.enabled_entity_groups:
        async_add_entities([])
        return
    entities = []
    for warning_type, level in WARNING_ENTITY_TITLES:
        if level not in coordinator.location.enabled_warning_levels:
            continue
        entity = HaWeatherJmaWarningBinarySensor(coordinator, warning_type, level)
        entity.entity_id = async_generate_entity_id(
            "binary_sensor.{}",
            f"ha_weather_jma_{coordinator.location.entry_slug}_{warning_type}_{level}",
            hass=hass,
        )
        entities.append(entity)
    async_add_entities(entities)


class HaWeatherJmaWarningBinarySensor(HaWeatherJmaBaseEntity, BinarySensorEntity):
    """Fixed warning type/level binary sensor."""

    _attr_device_class = BinarySensorDeviceClass.SAFETY
    _attr_translation_key = "warning_status"

    def __init__(
        self,
        coordinator: HaWeatherJmaCoordinator,
        warning_type: str,
        level: str,
    ) -> None:
        super().__init__(
            coordinator,
            f"ha_weather_jma_{coordinator.location.entry_id}_{warning_type}_{level}",
        )
        self._warning_type = warning_type
        self._level = level
        self._attr_translation_placeholders = {
            "warning_name": warning_entity_title(warning_type, level),
        }

    @property
    def is_on(self) -> bool | None:
        item = self.snapshot.alerts[(self._warning_type, self._level)]
        return item.is_active

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        item = self.snapshot.alerts[(self._warning_type, self._level)]
        return {
            "area_code": item.area_code,
            "area_name": item.area_name,
            "warning_code": item.warning_code,
            "report_datetime": item.report_datetime,
            "publishing_office": item.publishing_office,
            "headline_text": item.headline_text,
            "status_text": item.status_text,
        }
