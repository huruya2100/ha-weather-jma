"""Home Assistant の button platform 実装。"""

from __future__ import annotations

from typing import Any

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
    """管理グループが有効な場合に手動更新ボタンを登録します。"""
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
    """Coordinator の即時更新を要求する管理用ボタン entity。"""

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
        """ボタン押下時に coordinator の即時更新を要求します。"""
        await self.coordinator.async_request_refresh()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """設定値と最終更新時刻を管理用属性として返します。"""
        return {
            "forecast_area_name": self.location.forecast_area_name,
            "forecast_area_code": self.location.forecast_area_code,
            "forecast_office_name": self.location.forecast_office_name,
            "forecast_office_code": self.location.forecast_office_code,
            "observation_station_name": self.location.observation_station_name,
            "observation_station_code": self.location.observation_station_code,
            "warning_area_name": self.location.warning_area_name,
            "warning_area_code": self.location.warning_area_code,
            "warning_office_code": self.location.warning_office_code,
            "latitude": self.location.latitude,
            "longitude": self.location.longitude,
            "update_interval_minutes": self.location.update_interval_minutes,
            "last_api_call_at": self.snapshot.last_api_call_at,
            "last_success_at": self.snapshot.last_success_at,
        }
