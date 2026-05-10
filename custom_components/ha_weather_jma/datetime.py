"""Home Assistant の datetime platform 実装。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from homeassistant.components.datetime import DateTimeEntity, DateTimeEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import async_generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DATETIME_LAST_API_CALL_AT,
    DATETIME_LAST_SUCCESS_AT,
    DOMAIN,
    ENTITY_GROUP_MANAGEMENT,
)
from .coordinator import HaWeatherJmaCoordinator
from .entity import HaWeatherJmaBaseEntity
from .parser import CoordinatorSnapshot

DateTimeReader = Callable[[CoordinatorSnapshot], datetime | None]


@dataclass(slots=True, frozen=True, kw_only=True)
class HaWeatherJmaDateTimeDescription(DateTimeEntityDescription):
    """スナップショットから datetime 値を読むための entity 定義。"""

    value_fn: DateTimeReader


DESCRIPTIONS: tuple[HaWeatherJmaDateTimeDescription, ...] = (
    HaWeatherJmaDateTimeDescription(
        key=DATETIME_LAST_API_CALL_AT,
        translation_key=DATETIME_LAST_API_CALL_AT,
        value_fn=lambda snapshot: snapshot.last_api_call_at,
    ),
    HaWeatherJmaDateTimeDescription(
        key=DATETIME_LAST_SUCCESS_AT,
        translation_key=DATETIME_LAST_SUCCESS_AT,
        value_fn=lambda snapshot: snapshot.last_success_at,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """管理グループが有効な場合に更新時刻 datetime entity を登録します。"""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    if ENTITY_GROUP_MANAGEMENT not in coordinator.location.enabled_entity_groups:
        return

    entities = []
    for description in DESCRIPTIONS:
        entity = HaWeatherJmaDateTimeEntity(coordinator, description)
        entity.entity_id = async_generate_entity_id(
            "datetime.{}",
            f"ha_weather_jma_{coordinator.location.entry_slug}_{description.key}",
            hass=hass,
        )
        entities.append(entity)
    async_add_entities(entities)


class HaWeatherJmaDateTimeEntity(HaWeatherJmaBaseEntity, DateTimeEntity):
    """最終 API 呼び出し時刻などを表示する read-only datetime entity。"""

    entity_description: HaWeatherJmaDateTimeDescription

    def __init__(
        self,
        coordinator: HaWeatherJmaCoordinator,
        description: HaWeatherJmaDateTimeDescription,
    ) -> None:
        super().__init__(
            coordinator,
            f"ha_weather_jma_{coordinator.location.entry_id}_{description.key}",
        )
        self.entity_description = description
        self._attr_translation_key = description.translation_key

    @property
    def native_value(self) -> datetime | None:
        """スナップショットから datetime entity の値を返します。"""
        return self.entity_description.value_fn(self.snapshot)
