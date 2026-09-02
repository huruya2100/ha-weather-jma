"""Home Assistant の sensor platform 実装。"""

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
    SENSOR_LAST_API_CALL_AT,
    SENSOR_LAST_SUCCESS_AT,
    SENSOR_PUBLISHING_OFFICE,
    SENSOR_REPORT_DATETIME,
    SENSOR_TODAY_PRECIP,
    SENSOR_TOMORROW_PRECIP,
    TEXT_FORECAST_AREA,
    TEXT_OBSERVATION_STATION,
    TEXT_WARNING_AREA,
)
from .coordinator import HaWeatherJmaCoordinator
from .entity import HaWeatherJmaBaseEntity
from .parser import (
    CoordinatorSnapshot,
    ForecastDaily,
    first_two_forecast_days,
    translate_warning_title_to_english,
)

StateReader = Callable[[CoordinatorSnapshot], Any]
AttrReader = Callable[[CoordinatorSnapshot], dict[str, Any]]


@dataclass(slots=True, frozen=True, kw_only=True)
class HaWeatherJmaSensorDescription(SensorEntityDescription):
    """値取得関数と属性取得関数を持つ sensor 定義。"""

    entity_group: str
    value_fn: StateReader
    attrs_fn: AttrReader


def _today(snapshot: CoordinatorSnapshot) -> ForecastDaily | None:
    """スナップショット内の日別予報から先頭日を返します。"""
    return first_two_forecast_days(snapshot.forecast_days)[0]


def _tomorrow(snapshot: CoordinatorSnapshot) -> ForecastDaily | None:
    """スナップショット内の日別予報から 2 日目を返します。"""
    return first_two_forecast_days(snapshot.forecast_days)[1]


def _target_date_attributes(day: ForecastDaily | None) -> dict[str, Any]:
    """日別 sensor に付ける対象日属性を組み立てます。"""
    return {"target_date": day.target_date.isoformat() if day is not None else None}


def _today_precip_probability(snapshot: CoordinatorSnapshot) -> int | None:
    """今日の降水確率を返します。"""
    day = _today(snapshot)
    return day.precip_probability_percent if day is not None else None


def _tomorrow_precip_probability(snapshot: CoordinatorSnapshot) -> int | None:
    """明日の降水確率を返します。"""
    day = _tomorrow(snapshot)
    return day.precip_probability_percent if day is not None else None


def _today_attributes(snapshot: CoordinatorSnapshot) -> dict[str, Any]:
    """今日 sensor の属性を返します。"""
    return _target_date_attributes(_today(snapshot))


def _tomorrow_attributes(snapshot: CoordinatorSnapshot) -> dict[str, Any]:
    """明日 sensor の属性を返します。"""
    return _target_date_attributes(_tomorrow(snapshot))


def _alert_summary_value(
    snapshot: CoordinatorSnapshot,
    *,
    english: bool = False,
) -> str | None:
    """発表中警報タイトルを読める文字列へ集約します。"""
    if snapshot.alert_summary.max_level is None:
        return None
    if not snapshot.alert_summary.active_titles:
        return "なし"
    if english:
        return " / ".join(
            translate_warning_title_to_english(title)
            for title in snapshot.alert_summary.active_titles
        )
    return "、".join(snapshot.alert_summary.active_titles)


def _forecast_coverage_attributes(snapshot: CoordinatorSnapshot) -> dict[str, Any]:
    """予報データがどの区域・観測所由来かをデバッグ用属性にまとめます。"""
    return {
        "forecast_area_code": snapshot.location.forecast_area_code,
        "forecast_area_name": snapshot.location.forecast_area_name,
        "prefecture_name": snapshot.location.prefecture_name,
        "observation_station_code": snapshot.location.observation_station_code,
        "observation_station_name": snapshot.location.observation_station_name,
        "weekly_forecast_enabled": snapshot.location.weekly_forecast_enabled,
        "weekly_forecast_area_code": snapshot.location.weekly_forecast_area_code,
        "weekly_forecast_area_name": snapshot.location.weekly_forecast_area_name,
        "weekly_weather_area_policy": _weekly_weather_area_policy(snapshot),
        "weekly_temperature_station_policy": (
            "Weekly temperatures are used only when JMA publishes values for "
            "the selected observation station. Representative stations are not "
            "substituted."
        ),
        "daily_forecast_coverage": [
            {
                "target_date": day.target_date.isoformat(),
                "weather_area_code": day.weather_area_code,
                "weather_area_name": day.weather_area_name,
                "temperature_station_code": day.temperature_station_code,
                "temperature_station_name": day.temperature_station_name,
                "has_weather": day.condition_code is not None,
                "has_precip_probability": day.precip_probability_percent is not None,
                "has_temperature": (
                    day.temp_min_c is not None or day.temp_max_c is not None
                ),
            }
            for day in snapshot.forecast_days
        ],
    }


def _weekly_weather_area_policy(snapshot: CoordinatorSnapshot) -> str:
    """保存済み設定に対応する週間予報地点ポリシーを説明します。"""
    location = snapshot.location
    if location.weekly_forecast_enabled is False:
        return "Weekly forecast weather, precipitation, and temperatures are disabled."
    if location.weekly_forecast_enabled is True:
        return (
            "Weekly weather and precipitation use the explicitly confirmed "
            f"area {location.weekly_forecast_area_name} "
            f"({location.weekly_forecast_area_code})."
        )
    return (
        "If JMA publishes weekly weather and precipitation for a single "
        "representative area instead of the selected forecast area, that "
        "representative area is used."
    )


DESCRIPTIONS: tuple[HaWeatherJmaSensorDescription, ...] = (
    HaWeatherJmaSensorDescription(
        key=SENSOR_REPORT_DATETIME,
        translation_key=SENSOR_REPORT_DATETIME,
        entity_group=ENTITY_GROUP_WEATHER_FORECAST,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda snapshot: snapshot.forecast_meta.report_datetime,
        attrs_fn=lambda snapshot: {
            "publishing_office": snapshot.forecast_meta.publishing_office,
            **_forecast_coverage_attributes(snapshot),
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
        key=TEXT_FORECAST_AREA,
        translation_key=TEXT_FORECAST_AREA,
        entity_group=ENTITY_GROUP_MANAGEMENT,
        value_fn=lambda snapshot: snapshot.location.forecast_area_name,
        attrs_fn=lambda snapshot: {
            "area_code": snapshot.location.forecast_area_code,
            "prefecture_name": snapshot.location.prefecture_name,
            "office_name": snapshot.location.forecast_office_name,
            "office_code": snapshot.location.forecast_office_code,
            "weekly_forecast_enabled": snapshot.location.weekly_forecast_enabled,
            "weekly_forecast_area_code": (
                snapshot.location.weekly_forecast_area_code
            ),
            "weekly_forecast_area_name": (
                snapshot.location.weekly_forecast_area_name
            ),
            "weekly_weather_area_policy": _weekly_weather_area_policy(snapshot),
        },
    ),
    HaWeatherJmaSensorDescription(
        key=TEXT_OBSERVATION_STATION,
        translation_key=TEXT_OBSERVATION_STATION,
        entity_group=ENTITY_GROUP_MANAGEMENT,
        value_fn=lambda snapshot: snapshot.location.observation_station_name,
        attrs_fn=lambda snapshot: {
            "station_code": snapshot.location.observation_station_code,
            "latitude": snapshot.location.latitude,
            "longitude": snapshot.location.longitude,
            "weekly_temperature_station_policy": (
                "Weekly temperatures are used only when JMA publishes values for "
                "this observation station. Representative stations are not "
                "substituted."
            ),
        },
    ),
    HaWeatherJmaSensorDescription(
        key=TEXT_WARNING_AREA,
        translation_key=TEXT_WARNING_AREA,
        entity_group=ENTITY_GROUP_MANAGEMENT,
        value_fn=lambda snapshot: snapshot.location.warning_area_name,
        attrs_fn=lambda snapshot: {
            "area_code": snapshot.location.warning_area_code,
            "prefecture_name": snapshot.location.prefecture_name,
            "office_code": snapshot.location.warning_office_code,
        },
    ),
    HaWeatherJmaSensorDescription(
        key=SENSOR_LAST_API_CALL_AT,
        translation_key=SENSOR_LAST_API_CALL_AT,
        entity_group=ENTITY_GROUP_MANAGEMENT,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda snapshot: snapshot.last_api_call_at,
        attrs_fn=lambda snapshot: {},
    ),
    HaWeatherJmaSensorDescription(
        key=SENSOR_LAST_SUCCESS_AT,
        translation_key=SENSOR_LAST_SUCCESS_AT,
        entity_group=ENTITY_GROUP_MANAGEMENT,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda snapshot: snapshot.last_success_at,
        attrs_fn=lambda snapshot: {},
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """設定で有効な sensor entity を Home Assistant へ登録します。"""
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
    """Description の関数で値と属性を読む汎用 sensor entity。"""

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
        """スナップショットから sensor の状態値を計算します。"""
        if self.entity_description.key == SENSOR_ALERT_SUMMARY:
            language = getattr(
                getattr(self.coordinator.hass, "config", None),
                "language",
                "",
            )
            if str(language).casefold().startswith("en"):
                return _alert_summary_value(self.snapshot, english=True)
        return self.entity_description.value_fn(self.snapshot)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """スナップショットから sensor の追加属性を計算します。"""
        return self.entity_description.attrs_fn(self.snapshot)
