"""Text platform for ha-weather-jma."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.text import TextEntity, TextEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import async_generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    ENTITY_GROUP_MANAGEMENT,
    TEXT_FORECAST_AREA,
    TEXT_OBSERVATION_STATION,
    TEXT_WARNING_AREA,
)
from .coordinator import HaWeatherJmaCoordinator
from .entity import HaWeatherJmaBaseEntity
from .parser import CoordinatorSnapshot

TextReader = Callable[[CoordinatorSnapshot], str | None]
AttrReader = Callable[[CoordinatorSnapshot], dict[str, Any]]


@dataclass(slots=True, frozen=True, kw_only=True)
class HaWeatherJmaTextDescription(TextEntityDescription):
    """ha-weather-jma text description."""

    value_fn: TextReader
    attrs_fn: AttrReader


DESCRIPTIONS: tuple[HaWeatherJmaTextDescription, ...] = (
    HaWeatherJmaTextDescription(
        key=TEXT_FORECAST_AREA,
        translation_key=TEXT_FORECAST_AREA,
        value_fn=lambda snapshot: snapshot.location.forecast_area_name,
        attrs_fn=lambda snapshot: {
            "area_code": snapshot.location.forecast_area_code,
            "office_name": snapshot.location.forecast_office_name,
            "office_code": snapshot.location.forecast_office_code,
        },
    ),
    HaWeatherJmaTextDescription(
        key=TEXT_OBSERVATION_STATION,
        translation_key=TEXT_OBSERVATION_STATION,
        value_fn=lambda snapshot: snapshot.location.observation_station_name,
        attrs_fn=lambda snapshot: {
            "station_code": snapshot.location.observation_station_code,
            "latitude": snapshot.location.latitude,
            "longitude": snapshot.location.longitude,
        },
    ),
    HaWeatherJmaTextDescription(
        key=TEXT_WARNING_AREA,
        translation_key=TEXT_WARNING_AREA,
        value_fn=lambda snapshot: snapshot.location.warning_area_name,
        attrs_fn=lambda snapshot: {
            "area_code": snapshot.location.warning_area_code,
            "office_code": snapshot.location.warning_office_code,
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the text platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    if ENTITY_GROUP_MANAGEMENT not in coordinator.location.enabled_entity_groups:
        return

    entities = []
    for description in DESCRIPTIONS:
        entity = HaWeatherJmaTextEntity(coordinator, description)
        entity.entity_id = async_generate_entity_id(
            "text.{}",
            f"ha_weather_jma_{coordinator.location.entry_slug}_{description.key}",
            hass=hass,
        )
        entities.append(entity)
    async_add_entities(entities)


class HaWeatherJmaTextEntity(HaWeatherJmaBaseEntity, TextEntity):
    """Text entity that reports management metadata."""

    entity_description: HaWeatherJmaTextDescription

    def __init__(
        self,
        coordinator: HaWeatherJmaCoordinator,
        description: HaWeatherJmaTextDescription,
    ) -> None:
        super().__init__(
            coordinator,
            f"ha_weather_jma_{coordinator.location.entry_id}_{description.key}",
        )
        self.entity_description = description
        self._attr_translation_key = description.translation_key

    @property
    def native_value(self) -> str | None:
        return self.entity_description.value_fn(self.snapshot)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.entity_description.attrs_fn(self.snapshot)
