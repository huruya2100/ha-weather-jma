"""Update coordinator for ha-weather-jma."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import HaWeatherJmaApiClient
from .const import DOMAIN
from .parser import (
    AlertSummary,
    CoordinatorSnapshot,
    ForecastAreaNotFoundError,
    ForecastDaily,
    ForecastMetadata,
    HaWeatherJmaParserError,
    LocationConfig,
    ObservationSnapshot,
    ObservationUnavailableError,
    WarningAreaNotFoundError,
    build_alert_summary,
    build_default_alerts,
    build_snapshot,
    parse_alerts_xml,
    parse_forecast,
    parse_forecast_metadata,
    parse_observation,
)

_LOGGER = logging.getLogger(__name__)


class HaWeatherJmaCoordinator(DataUpdateCoordinator[CoordinatorSnapshot]):
    """Coordinate updates from JMA APIs."""

    def __init__(
        self,
        hass: HomeAssistant,
        api_client: HaWeatherJmaApiClient,
        location: LocationConfig,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{location.entry_id}",
            update_interval=None,
        )
        self._api_client = api_client
        self.location = location
        self.update_interval = self._suggest_interval()

    def _suggest_interval(self) -> timedelta:
        return timedelta(minutes=self.location.update_interval_minutes)

    async def _async_update_data(self) -> CoordinatorSnapshot:
        previous = self.data if isinstance(self.data, CoordinatorSnapshot) else None

        latest_time: str | None = None
        observation: ObservationSnapshot | None = None
        observation_failed = False
        forecast_days: tuple[ForecastDaily, ...] = ()
        forecast_meta = ForecastMetadata(report_datetime=None, publishing_office=None)
        forecast_failed = False
        alerts = build_default_alerts(
            warning_area_code=self.location.warning_area_code,
            warning_area_name=self.location.warning_area_name,
            report_datetime=None,
            publishing_office=None,
            headline_text=None,
            unavailable=False,
        )
        warning_failed = False

        try:
            latest_time = await self._api_client.fetch_amedas_latest_time()
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            observation_failed = True
            _LOGGER.warning("Failed to fetch latest AMeDAS time: %s", err)

        tasks: dict[str, asyncio.Task[object]] = {
            "forecast": asyncio.create_task(
                self._api_client.fetch_forecast(self.location.forecast_office_code)
            ),
            "warnings": asyncio.create_task(
                self._api_client.fetch_warning_xml_documents(
                    self.location.warning_office_code
                )
            ),
        }
        if latest_time is not None:
            tasks["observation"] = asyncio.create_task(
                self._api_client.fetch_amedas_observation(
                    self.location.observation_station_code,
                    latest_time,
                )
            )

        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        result_map = dict(zip(tasks.keys(), results, strict=False))

        if latest_time is not None:
            raw_observation = result_map.get("observation")
            if isinstance(raw_observation, Exception):
                observation_failed = True
                _LOGGER.warning("Observation fetch failed: %s", raw_observation)
            elif isinstance(raw_observation, Mapping):
                try:
                    observation = parse_observation(raw_observation, latest_time)
                except ObservationUnavailableError as err:
                    observation_failed = True
                    _LOGGER.warning("Observation normalization failed: %s", err)
            else:
                observation_failed = True
                _LOGGER.warning("Observation fetch returned unexpected payload type")

        raw_forecast = result_map.get("forecast")
        if isinstance(raw_forecast, Exception):
            forecast_failed = True
            _LOGGER.warning("Forecast fetch failed: %s", raw_forecast)
        elif isinstance(raw_forecast, list):
            try:
                forecast_days = parse_forecast(
                    raw_forecast,
                    self.location.forecast_area_code,
                    self.location.observation_station_code,
                )
                forecast_meta = parse_forecast_metadata(raw_forecast)
            except ForecastAreaNotFoundError as err:
                raise UpdateFailed(str(err)) from err
            except HaWeatherJmaParserError as err:
                forecast_failed = True
                _LOGGER.warning("Forecast normalization failed: %s", err)
        else:
            forecast_failed = True
            _LOGGER.warning("Forecast fetch returned unexpected payload type")

        raw_warnings = result_map.get("warnings")
        if isinstance(raw_warnings, Exception):
            warning_failed = True
            _LOGGER.warning("Warning fetch failed: %s", raw_warnings)
        elif isinstance(raw_warnings, list) and all(
            isinstance(document, str) for document in raw_warnings
        ):
            try:
                alerts = parse_alerts_xml(
                    raw_warnings,
                    self.location.warning_area_code,
                    self.location.warning_area_name,
                )
            except WarningAreaNotFoundError as err:
                warning_failed = True
                _LOGGER.warning("Warning area missing in payload: %s", err)
            except HaWeatherJmaParserError as err:
                warning_failed = True
                _LOGGER.warning("Warning normalization failed: %s", err)
        else:
            warning_failed = True
            _LOGGER.warning("Warning fetch returned unexpected payload type")

        if observation_failed and forecast_failed and warning_failed:
            if previous is None:
                raise UpdateFailed("All JMA data sources failed")

            _LOGGER.warning(
                "All JMA data sources failed; reusing the previous snapshot"
            )
            return build_snapshot(
                location=self.location,
                observation=previous.observation,
                forecast_days=previous.forecast_days,
                forecast_meta=previous.forecast_meta,
                alerts=previous.alerts,
                alert_summary=previous.alert_summary,
                last_success_at=previous.last_success_at,
                is_partial=True,
            )

        is_partial = observation_failed or forecast_failed or warning_failed

        if observation_failed:
            observation = previous.observation if previous is not None else None

        if forecast_failed:
            if previous is not None:
                forecast_days = previous.forecast_days
                forecast_meta = previous.forecast_meta
            else:
                forecast_days = ()
                forecast_meta = ForecastMetadata(
                    report_datetime=None, publishing_office=None
                )

        if warning_failed:
            alerts = build_default_alerts(
                warning_area_code=self.location.warning_area_code,
                warning_area_name=self.location.warning_area_name,
                report_datetime=None,
                publishing_office=None,
                headline_text=None,
                unavailable=True,
            )

        alert_summary: AlertSummary = build_alert_summary(alerts)
        return build_snapshot(
            location=self.location,
            observation=observation,
            forecast_days=forecast_days,
            forecast_meta=forecast_meta,
            alerts=alerts,
            alert_summary=alert_summary,
            last_success_at=datetime.now(timezone.utc),
            is_partial=is_partial,
        )
