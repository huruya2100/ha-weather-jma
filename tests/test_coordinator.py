"""Coordinator-focused regression tests."""

from __future__ import annotations

import asyncio
import unittest

from tests import support as SUPPORT

LOADED = SUPPORT.load_modules("coordinator", "parser")
COORDINATOR = LOADED["coordinator"]
PARSER = LOADED["parser"]
HA_CORE = SUPPORT.get_stub_module("homeassistant.core")
UPDATE_COORDINATOR = SUPPORT.get_stub_module("homeassistant.helpers.update_coordinator")


class FakeApiClient:
    """Configurable async API stub."""

    def __init__(
        self,
        *,
        latest_time,
        observation,
        forecast,
        warnings,
    ) -> None:
        self.latest_time = latest_time
        self.observation = observation
        self.forecast = forecast
        self.warnings = warnings

    async def fetch_amedas_latest_time(self) -> str:
        if isinstance(self.latest_time, Exception):
            raise self.latest_time
        return self.latest_time

    async def fetch_amedas_observation(self, station_code: str, latest_time: str):
        del station_code, latest_time
        if isinstance(self.observation, Exception):
            raise self.observation
        return self.observation

    async def fetch_forecast(self, office_code: str):
        del office_code
        if isinstance(self.forecast, Exception):
            raise self.forecast
        return self.forecast

    async def fetch_warning_xml_documents(self, office_code: str):
        del office_code
        if isinstance(self.warnings, Exception):
            raise self.warnings
        return self.warnings


def build_location():
    """Build a shared location config."""
    return PARSER.build_location_config(
        "entry-123",
        "東京",
        {
            "forecast_area_code": "130010",
            "forecast_area_name": "東京地方",
            "forecast_office_code": "130000",
            "forecast_office_name": "気象庁",
            "observation_station_code": "44132",
            "observation_station_name": "東京",
            "warning_area_code": "1310100",
            "warning_area_name": "千代田区",
            "warning_office_code": "130000",
            "latitude": 35.6916,
            "longitude": 139.75,
            "update_interval_minutes": 10,
            "enabled_warning_levels": [
                "advisory",
                "warning",
                "danger_warning",
                "emergency_warning",
            ],
        },
    )


def build_previous_snapshot():
    """Build a snapshot used for fallback assertions."""
    forecast = SUPPORT.read_fixture("forecast_normal.json")
    warnings = [SUPPORT.read_text_fixture("warning_xml_current.xml")]
    latest_time = "2026-04-14T20:40:00+09:00"
    observation = PARSER.parse_observation(
        SUPPORT.read_fixture("amedas_observation_normal.json"),
        latest_time,
    )
    forecast_days = PARSER.parse_forecast(forecast, "130010", "44132")
    forecast_meta = PARSER.parse_forecast_metadata(forecast)
    alerts = PARSER.parse_alerts_xml(warnings, "1310100", "千代田区")
    return PARSER.build_snapshot(
        location=build_location(),
        observation=observation,
        forecast_days=forecast_days,
        forecast_meta=forecast_meta,
        alerts=alerts,
        alert_summary=PARSER.build_alert_summary(alerts),
        last_api_call_at=PARSER.parse_datetime("2026-04-14T11:55:00+00:00"),
        last_success_at=PARSER.parse_datetime("2026-04-14T11:50:00+00:00"),
        is_partial=False,
    )


class CoordinatorTests(unittest.TestCase):
    """Test cases derived from the test design document."""

    def test_all_fetches_success_builds_complete_snapshot(self) -> None:
        coordinator = COORDINATOR.HaWeatherJmaCoordinator(
            HA_CORE.HomeAssistant(),
            FakeApiClient(
                latest_time="2026-04-14T20:40:00+09:00",
                observation=SUPPORT.read_fixture("amedas_observation_normal.json"),
                forecast=SUPPORT.read_fixture("forecast_normal.json"),
                warnings=[SUPPORT.read_text_fixture("warning_xml_current.xml")],
            ),
            build_location(),
        )

        snapshot = asyncio.run(coordinator._async_update_data())

        self.assertFalse(snapshot.is_partial)
        self.assertIsNotNone(snapshot.observation)
        self.assertEqual(len(snapshot.forecast_days), 3)
        self.assertEqual(snapshot.alert_summary.max_level, "advisory")
        self.assertIsNotNone(snapshot.last_api_call_at)
        self.assertEqual(snapshot.last_success_at, snapshot.last_api_call_at)

    def test_observation_only_failure_keeps_previous_observation_and_marks_partial(
        self,
    ) -> None:
        coordinator = COORDINATOR.HaWeatherJmaCoordinator(
            HA_CORE.HomeAssistant(),
            FakeApiClient(
                latest_time="2026-04-14T21:40:00+09:00",
                observation=LookupError("missing observation"),
                forecast=SUPPORT.read_fixture("forecast_normal.json"),
                warnings=[SUPPORT.read_text_fixture("warning_xml_current.xml")],
            ),
            build_location(),
        )
        coordinator.data = build_previous_snapshot()

        snapshot = asyncio.run(coordinator._async_update_data())

        self.assertTrue(snapshot.is_partial)
        self.assertEqual(snapshot.observation, coordinator.data.observation)
        self.assertEqual(len(snapshot.forecast_days), 3)

    def test_forecast_only_failure_reuses_previous_forecast_and_marks_partial(
        self,
    ) -> None:
        coordinator = COORDINATOR.HaWeatherJmaCoordinator(
            HA_CORE.HomeAssistant(),
            FakeApiClient(
                latest_time="2026-04-14T20:40:00+09:00",
                observation=SUPPORT.read_fixture("amedas_observation_normal.json"),
                forecast=ValueError("broken forecast"),
                warnings=[SUPPORT.read_text_fixture("warning_xml_current.xml")],
            ),
            build_location(),
        )
        coordinator.data = build_previous_snapshot()

        snapshot = asyncio.run(coordinator._async_update_data())

        self.assertTrue(snapshot.is_partial)
        self.assertEqual(snapshot.forecast_days, coordinator.data.forecast_days)
        self.assertEqual(snapshot.forecast_meta, coordinator.data.forecast_meta)

    def test_warning_only_failure_marks_alerts_unknown(self) -> None:
        coordinator = COORDINATOR.HaWeatherJmaCoordinator(
            HA_CORE.HomeAssistant(),
            FakeApiClient(
                latest_time="2026-04-14T20:40:00+09:00",
                observation=SUPPORT.read_fixture("amedas_observation_normal.json"),
                forecast=SUPPORT.read_fixture("forecast_normal.json"),
                warnings=ValueError("warning fetch failed"),
            ),
            build_location(),
        )

        snapshot = asyncio.run(coordinator._async_update_data())

        self.assertTrue(snapshot.is_partial)
        self.assertIsNone(snapshot.alert_summary.max_level)
        self.assertTrue(
            all(item.is_active is None for item in snapshot.alerts.values())
        )

    def test_all_fetches_fail_with_previous_snapshot_reuses_existing_data(self) -> None:
        coordinator = COORDINATOR.HaWeatherJmaCoordinator(
            HA_CORE.HomeAssistant(),
            FakeApiClient(
                latest_time=ValueError("latest time failed"),
                observation=LookupError("missing observation"),
                forecast=ValueError("forecast failed"),
                warnings=ValueError("warning failed"),
            ),
            build_location(),
        )
        previous_snapshot = build_previous_snapshot()
        coordinator.data = previous_snapshot

        snapshot = asyncio.run(coordinator._async_update_data())

        self.assertTrue(snapshot.is_partial)
        self.assertEqual(snapshot.observation, previous_snapshot.observation)
        self.assertEqual(snapshot.forecast_days, previous_snapshot.forecast_days)
        self.assertEqual(snapshot.forecast_meta, previous_snapshot.forecast_meta)
        self.assertEqual(snapshot.alerts, previous_snapshot.alerts)
        self.assertEqual(snapshot.alert_summary, previous_snapshot.alert_summary)
        self.assertNotEqual(snapshot.last_api_call_at, previous_snapshot.last_api_call_at)
        self.assertEqual(snapshot.last_success_at, previous_snapshot.last_success_at)

    def test_all_fetches_fail_without_previous_snapshot_raises_update_failed(self) -> None:
        coordinator = COORDINATOR.HaWeatherJmaCoordinator(
            HA_CORE.HomeAssistant(),
            FakeApiClient(
                latest_time=ValueError("latest time failed"),
                observation=LookupError("missing observation"),
                forecast=ValueError("forecast failed"),
                warnings=ValueError("warning failed"),
            ),
            build_location(),
        )

        with self.assertRaises(UPDATE_COORDINATOR.UpdateFailed):
            asyncio.run(coordinator._async_update_data())


if __name__ == "__main__":
    unittest.main()
