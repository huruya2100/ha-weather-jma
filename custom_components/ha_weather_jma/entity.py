"""Entity base classes for ha-weather-jma."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN, MANUFACTURER, MODEL
from .coordinator import HaWeatherJmaCoordinator
from .parser import CoordinatorSnapshot, LocationConfig


class HaWeatherJmaBaseEntity(CoordinatorEntity[HaWeatherJmaCoordinator]):
    """Shared coordinator-backed entity."""

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
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def snapshot(self) -> CoordinatorSnapshot:
        """Return the latest coordinator snapshot."""
        return self.coordinator.data

    @property
    def location(self) -> LocationConfig:
        """Return the normalized config entry."""
        return self.coordinator.location

    def _base_location_attributes(self) -> dict[str, Any]:
        return {
            "forecast_area_name": self.location.forecast_area_name,
            "forecast_area_code": self.location.forecast_area_code,
            "observation_station_name": self.location.observation_station_name,
            "observation_station_code": self.location.observation_station_code,
            "warning_area_name": self.location.warning_area_name,
            "warning_area_code": self.location.warning_area_code,
            "is_partial": self.snapshot.is_partial if self.snapshot else None,
        }
