"""ha-weather-jma の各 entity が共有する基底実装。"""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN, MANUFACTURER, MODEL
from .coordinator import HaWeatherJmaCoordinator
from .parser import CoordinatorSnapshot, LocationConfig


class HaWeatherJmaBaseEntity(CoordinatorEntity[HaWeatherJmaCoordinator]):
    """CoordinatorSnapshot を読む全 entity 共通の基底クラス。

    unique_id、デバイス情報、地域属性をここで統一し、各 platform 実装では
    表示する値だけに集中できるようにしています。
    """

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HaWeatherJmaCoordinator,
        unique_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = unique_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.location.entry_id)},
            name=coordinator.location.name,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    @property
    def snapshot(self) -> CoordinatorSnapshot:
        """Coordinator が保持する最新スナップショットを返します。"""
        return self.coordinator.data

    @property
    def location(self) -> LocationConfig:
        """正規化済みの設定値を返します。"""
        return self.coordinator.location

    def _base_location_attributes(self) -> dict[str, Any]:
        """多くの entity で共通表示する地域・観測所属性を組み立てます。"""
        return {
            "prefecture_name": self.location.prefecture_name,
            "forecast_area_name": self.location.forecast_area_name,
            "forecast_area_code": self.location.forecast_area_code,
            "observation_station_name": self.location.observation_station_name,
            "observation_station_code": self.location.observation_station_code,
            "warning_area_name": self.location.warning_area_name,
            "warning_area_code": self.location.warning_area_code,
            "is_partial": self.snapshot.is_partial if self.snapshot else None,
        }
