"""Sensor platform for ha-weather-jma."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import async_generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    ENTITY_GROUP_MANAGEMENT,
    ENTITY_GROUP_WARNINGS,
    ENTITY_GROUP_WEATHER_FORECAST,
    SENSOR_ALERT_MAX_LEVEL,
    SENSOR_ALERT_SUMMARY,
    SENSOR_FORECAST_AREA,
    SENSOR_LAST_API_CALL_AT,
    SENSOR_OBSERVATION_STATION,
    SENSOR_PUBLISHING_OFFICE,
    SENSOR_REPORT_DATETIME,
    SENSOR_TODAY_PRECIP,
    SENSOR_TOMORROW_PRECIP,
)
from .coordinator import HaWeatherJmaCoordinator
from .entity import HaWeatherJmaBaseEntity
from .parser import CoordinatorSnapshot, ForecastDaily, first_two_forecast_days

StateReader = Callable[[CoordinatorSnapshot], Any]
AttrReader = Callable[[CoordinatorSnapshot], dict[str, Any]]


@dataclass(slots=True, frozen=True, kw_only=True)
class HaWeatherJmaSensorDescription(SensorEntityDescription):
    """ha-weather-jma sensor description."""

    entity_group: str
    value_fn: StateReader
    attrs_fn: AttrReader


def _today(snapshot: CoordinatorSnapshot) -> ForecastDaily | None:
    return first_two_forecast_days(snapshot.forecast_days)[0]


def _tomorrow(snapshot: CoordinatorSnapshot) -> ForecastDaily | None:
    return first_two_forecast_days(snapshot.forecast_days)[1]


def _target_date_attributes(day: ForecastDaily | None) -> dict[str, Any]:
    return {"target_date": day.target_date.isoformat() if day is not None else None}


def _today_precip_probability(snapshot: CoordinatorSnapshot) -> int | None:
    day = _today(snapshot)
    return day.precip_probability_percent if day is not None else None


def _tomorrow_precip_probability(snapshot: CoordinatorSnapshot) -> int | None:
    day = _tomorrow(snapshot)
    return day.precip_probability_percent if day is not None else None


def _today_attributes(snapshot: CoordinatorSnapshot) -> dict[str, Any]:
    return _target_date_attributes(_today(snapshot))


def _tomorrow_attributes(snapshot: CoordinatorSnapshot) -> dict[str, Any]:
    return _target_date_attributes(_tomorrow(snapshot))


def _alert_summary_value(snapshot: CoordinatorSnapshot) -> str | None:
    if snapshot.alert_summary.max_level is None:
        return None
    if not snapshot.alert_summary.active_titles:
        return "なし"
    return "、".join(snapshot.alert_summary.active_titles)


DESCRIPTIONS: tuple[HaWeatherJmaSensorDescription, ...] = (
    HaWeatherJmaSensorDescription(
        key=SENSOR_FORECAST_AREA,
        translation_key=SENSOR_FORECAST_AREA,
        entity_group=ENTITY_GROUP_MANAGEMENT,
        value_fn=lambda snapshot: snapshot.location.forecast_area_name,
        attrs_fn=lambda snapshot: {
            "area_code": snapshot.location.forecast_area_code,
            "office_code": snapshot.location.forecast_office_code,
            "office_name": snapshot.location.forecast_office_name,
        },
    ),
    HaWeatherJmaSensorDescription(
        key=SENSOR_OBSERVATION_STATION,
        translation_key=SENSOR_OBSERVATION_STATION,
        entity_group=ENTITY_GROUP_MANAGEMENT,
        value_fn=lambda snapshot: snapshot.location.observation_station_name,
        attrs_fn=lambda snapshot: {
            "station_code": snapshot.location.observation_station_code,
            "latitude": snapshot.location.latitude,
            "longitude": snapshot.location.longitude,
        },
    ),
    HaWeatherJmaSensorDescription(
        key=SENSOR_REPORT_DATETIME,
        translation_key=SENSOR_REPORT_DATETIME,
        entity_group=ENTITY_GROUP_WEATHER_FORECAST,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda snapshot: snapshot.forecast_meta.report_datetime,
        attrs_fn=lambda snapshot: {
            "publishing_office": snapshot.forecast_meta.publishing_office,
        },
    ),
    HaWeatherJmaSensorDescription(
        key=SENSOR_PUBLISHING_OFFICE,
        translation_key=SENSOR_PUBLISHING_OFFICE,
        entity_group=ENTITY_GROUP_WEATHER_FORECAST,
        value_fn=lambda snapshot: snapshot.forecast_meta.publishing_office,
        attrs_fn=lambda snapshot: {},
    ),
    HaWeatherJmaSensorDescription(
        key=SENSOR_TODAY_PRECIP,
        translation_key=SENSOR_TODAY_PRECIP,
        entity_group=ENTITY_GROUP_WEATHER_FORECAST,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=_today_precip_probability,
        attrs_fn=_today_attributes,
    ),
    HaWeatherJmaSensorDescription(
        key=SENSOR_TOMORROW_PRECIP,
        translation_key=SENSOR_TOMORROW_PRECIP,
        entity_group=ENTITY_GROUP_WEATHER_FORECAST,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=_tomorrow_precip_probability,
        attrs_fn=_tomorrow_attributes,
    ),
    HaWeatherJmaSensorDescription(
        key=SENSOR_ALERT_SUMMARY,
        translation_key=SENSOR_ALERT_SUMMARY,
        entity_group=ENTITY_GROUP_WARNINGS,
        value_fn=_alert_summary_value,
        attrs_fn=lambda snapshot: {
            "active_types": list(snapshot.alert_summary.active_types),
            "active_titles": list(snapshot.alert_summary.active_titles),
            "headline_text": snapshot.alert_summary.headline_text,
            "report_datetime": snapshot.alert_summary.report_datetime,
            "publishing_office": snapshot.alert_summary.publishing_office,
        },
    ),
    HaWeatherJmaSensorDescription(
        key=SENSOR_ALERT_MAX_LEVEL,
        translation_key=SENSOR_ALERT_MAX_LEVEL,
        entity_group=ENTITY_GROUP_WARNINGS,
        value_fn=lambda snapshot: snapshot.alert_summary.max_level,
        attrs_fn=lambda snapshot: {
            "active_types": list(snapshot.alert_summary.active_types),
        },
    ),
    HaWeatherJmaSensorDescription(
        key=SENSOR_LAST_API_CALL_AT,
        translation_key=SENSOR_LAST_API_CALL_AT,
        entity_group=ENTITY_GROUP_MANAGEMENT,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda snapshot: snapshot.last_api_call_at,
        attrs_fn=lambda snapshot: {
            "last_success_at": snapshot.last_success_at,
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for description in DESCRIPTIONS:
        if description.entity_group not in coordinator.location.enabled_entity_groups:
            continue
        entity = HaWeatherJmaSensorEntity(coordinator, description)
        entity.entity_id = async_generate_entity_id(
            "sensor.{}",
            f"ha_weather_jma_{coordinator.location.entry_slug}_{description.key}",
            hass=hass,
        )
        entities.append(entity)
    async_add_entities(entities)


class HaWeatherJmaSensorEntity(HaWeatherJmaBaseEntity, SensorEntity):
    """Coordinator-backed ha-weather-jma sensor."""

    entity_description: HaWeatherJmaSensorDescription

    def __init__(
        self,
        coordinator: HaWeatherJmaCoordinator,
        description: HaWeatherJmaSensorDescription,
    ) -> None:
        super().__init__(
            coordinator,
            f"ha_weather_jma_{coordinator.location.entry_id}_{description.key}",
        )
        self.entity_description = description
        self._attr_translation_key = description.translation_key
        self._attr_device_class = description.device_class
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.snapshot)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.entity_description.attrs_fn(self.snapshot)
