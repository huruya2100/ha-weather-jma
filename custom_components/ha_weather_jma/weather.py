"""Weather platform for ha-weather-jma."""

from __future__ import annotations

from typing import Any

from homeassistant.components.weather import WeatherEntity, WeatherEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPressure, UnitOfSpeed, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import async_generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HaWeatherJmaCoordinator
from .entity import HaWeatherJmaBaseEntity
from .parser import (
    forecast_datetime_utc,
    map_condition_to_ha,
    resolve_weather_condition,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the weather platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entity = HaWeatherJmaEntity(coordinator)
    entity.entity_id = async_generate_entity_id(
        "weather.{}",
        f"ha_weather_jma_{coordinator.location.entry_slug}",
        hass=hass,
    )
    async_add_entities([entity])


class HaWeatherJmaEntity(HaWeatherJmaBaseEntity, WeatherEntity):
    """Main ha-weather-jma weather entity."""

    _attr_supported_features = WeatherEntityFeature.FORECAST_DAILY
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_wind_speed_unit = UnitOfSpeed.METERS_PER_SECOND
    _attr_translation_key = "weather"

    def __init__(self, coordinator: HaWeatherJmaCoordinator) -> None:
        super().__init__(
            coordinator,
            f"ha_weather_jma_{coordinator.location.entry_id}_weather",
        )

    @property
    def condition(self) -> str:
        condition, _ = resolve_weather_condition(
            self.snapshot.observation, self.snapshot.forecast_days
        )
        return condition

    @property
    def native_temperature(self) -> float | None:
        observation = self.snapshot.observation
        return observation.temperature_c if observation is not None else None

    @property
    def humidity(self) -> int | None:
        observation = self.snapshot.observation
        return observation.humidity_percent if observation is not None else None

    @property
    def native_pressure(self) -> float | None:
        observation = self.snapshot.observation
        return observation.pressure_hpa if observation is not None else None

    @property
    def native_wind_speed(self) -> float | None:
        observation = self.snapshot.observation
        return observation.wind_speed_ms if observation is not None else None

    @property
    def wind_bearing(self) -> int | None:
        observation = self.snapshot.observation
        return observation.wind_direction_deg if observation is not None else None

    async def async_forecast_daily(self) -> list[dict[str, Any]] | None:
        """Return the daily forecast."""
        observation = self.snapshot.observation
        fallback_temperature = (
            observation.temperature_c if observation is not None else None
        )
        return [
            {
                "datetime": forecast_datetime_utc(day.target_date),
                "condition": map_condition_to_ha(
                    day.condition_code, day.condition_text
                ),
                "native_temperature": (
                    day.temp_max_c
                    if day.temp_max_c is not None
                    else (
                        day.temp_min_c
                        if day.temp_min_c is not None
                        else fallback_temperature
                    )
                ),
                "native_templow": day.temp_min_c,
                "precipitation_probability": day.precip_probability_percent,
            }
            for day in self.snapshot.forecast_days
        ]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attributes = self._base_location_attributes()
        attributes.update(
            {
                "report_datetime": self.snapshot.forecast_meta.report_datetime,
                "publishing_office": self.snapshot.forecast_meta.publishing_office,
            }
        )
        _, raw_condition_text = resolve_weather_condition(
            self.snapshot.observation,
            self.snapshot.forecast_days,
        )
        if raw_condition_text is not None:
            attributes["raw_condition_text"] = raw_condition_text
        return attributes

    @callback
    def _handle_coordinator_update(self) -> None:
        super()._handle_coordinator_update()
        if self.hass is not None:
            self.hass.async_create_task(self.async_update_listeners())
