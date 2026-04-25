"""Entity behavior regression tests."""

from __future__ import annotations

import asyncio
import types
import unittest
from typing import Any

from tests.support import load_modules, read_fixture, read_text_fixture

LOADED = load_modules("binary_sensor", "button", "sensor", "weather", "parser")
BINARY_SENSOR = LOADED["binary_sensor"]
BUTTON = LOADED["button"]
PARSER = LOADED["parser"]
SENSOR = LOADED["sensor"]
WEATHER = LOADED["weather"]


def build_location(enabled_entity_groups=None):
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
            "enabled_entity_groups": enabled_entity_groups
            or [
                "forecast_sensors",
                "warning_summary",
                "warning_binary_sensors",
                "location_info",
                "actions",
            ],
        },
    )


def build_snapshot(*, observation=None, alerts=None):
    forecast_payload = read_fixture("forecast_normal.json")
    location = build_location()
    forecast_days = PARSER.parse_forecast(forecast_payload, "130010", "44132")
    forecast_meta = PARSER.parse_forecast_metadata(forecast_payload)
    alert_items = alerts or PARSER.parse_alerts_xml(
        [read_text_fixture("warning_xml_current.xml")],
        "1310100",
        "千代田区",
    )
    return PARSER.build_snapshot(
        location=location,
        observation=observation,
        forecast_days=forecast_days,
        forecast_meta=forecast_meta,
        alerts=alert_items,
        alert_summary=PARSER.build_alert_summary(alert_items),
        last_api_call_at=PARSER.parse_datetime("2026-04-14T11:55:00+00:00"),
        last_success_at=PARSER.parse_datetime("2026-04-14T11:50:00+00:00"),
        is_partial=False,
    )


def build_coordinator(snapshot):
    return types.SimpleNamespace(location=snapshot.location, data=snapshot, hass=None)


class EntityTests(unittest.TestCase):
    """Entity-level tests based on the design cases."""

    def test_weather_condition_prefers_observation_code(self) -> None:
        snapshot = build_snapshot(
            observation=PARSER.parse_observation(
                read_fixture("amedas_observation_normal.json"),
                "2026-04-14T20:40:00+09:00",
            )
        )
        entity = WEATHER.HaWeatherJmaEntity(build_coordinator(snapshot))

        self.assertEqual(entity.condition, "sunny")
        self.assertEqual(entity.native_temperature, 18.1)
        self.assertEqual(entity.humidity, 77)
        self.assertEqual(entity.wind_bearing, 135)

    def test_weather_condition_falls_back_to_today_forecast_when_observation_missing(
        self,
    ) -> None:
        snapshot = build_snapshot(observation=None)
        entity = WEATHER.HaWeatherJmaEntity(build_coordinator(snapshot))

        self.assertEqual(entity.condition, "cloudy")
        self.assertEqual(entity.extra_state_attributes["raw_condition_text"], "くもり")

    def test_weather_forecast_formats_multiple_days(self) -> None:
        snapshot = build_snapshot(
            observation=PARSER.parse_observation(
                read_fixture("amedas_observation_normal.json"),
                "2026-04-14T20:40:00+09:00",
            )
        )
        entity = WEATHER.HaWeatherJmaEntity(build_coordinator(snapshot))

        forecast = asyncio.run(entity.async_forecast_daily())

        self.assertGreaterEqual(len(forecast), 2)
        self.assertEqual(forecast[0]["condition"], "cloudy")
        self.assertEqual(forecast[1]["native_temperature"], 21.0)
        self.assertEqual(forecast[1]["native_templow"], 14.0)

    def test_alert_summary_sensor_returns_none_when_warning_fetch_failed(self) -> None:
        alerts = PARSER.build_default_alerts(
            warning_area_code="1310100",
            warning_area_name="千代田区",
            report_datetime=None,
            publishing_office=None,
            headline_text=None,
            unavailable=True,
        )
        snapshot = build_snapshot(observation=None, alerts=alerts)
        description = next(
            item for item in SENSOR.DESCRIPTIONS if item.key == "alert_summary"
        )
        entity = SENSOR.HaWeatherJmaSensorEntity(
            build_coordinator(snapshot),
            description,
        )

        self.assertIsNone(entity.native_value)
        self.assertEqual(entity.extra_state_attributes["active_titles"], [])

    def test_entity_metadata_does_not_present_the_integration_as_official(self) -> None:
        snapshot = build_snapshot(observation=None)
        entity = WEATHER.HaWeatherJmaEntity(build_coordinator(snapshot))

        self.assertEqual(
            entity._attr_attribution,
            "Unofficial integration using data published by the "
            "Japan Meteorological Agency",
        )
        self.assertEqual(
            entity._attr_device_info["manufacturer"],
            "Home Assistant custom integration",
        )
        self.assertEqual(entity._attr_device_info["model"], "ha-weather-jma")

    def test_alert_max_level_sensor_reports_warning_level(self) -> None:
        alerts = PARSER.parse_alerts_xml(
            [
                read_text_fixture("warning_xml_current.xml"),
                read_text_fixture("warning_xml_heavyrain_level4.xml"),
            ],
            "1310100",
            "千代田区",
        )
        snapshot = build_snapshot(observation=None, alerts=alerts)
        description = next(
            item for item in SENSOR.DESCRIPTIONS if item.key == "alert_max_level"
        )
        entity = SENSOR.HaWeatherJmaSensorEntity(
            build_coordinator(snapshot),
            description,
        )

        self.assertEqual(entity.native_value, "danger_warning")
        self.assertIn("heavy_rain", entity.extra_state_attributes["active_types"])

    def test_last_api_call_sensor_reports_timestamp(self) -> None:
        snapshot = build_snapshot(observation=None)
        description = next(
            item for item in SENSOR.DESCRIPTIONS if item.key == "last_api_call_at"
        )
        entity = SENSOR.HaWeatherJmaSensorEntity(
            build_coordinator(snapshot),
            description,
        )

        self.assertEqual(entity.native_value, snapshot.last_api_call_at)
        self.assertEqual(
            entity.extra_state_attributes["last_success_at"],
            snapshot.last_success_at,
        )

    def test_binary_sensor_is_off_when_warning_cleared(self) -> None:
        alerts = PARSER.parse_alerts_xml(
            ["""<?xml version="1.0" encoding="UTF-8"?>
<Report xmlns="http://xml.kishou.go.jp/jmaxml1/">
  <Control><PublishingOffice>気象庁</PublishingOffice></Control>
  <Head xmlns="http://xml.kishou.go.jp/jmaxml1/informationBasis1/">
    <ReportDateTime>2026-05-29T01:20:00+09:00</ReportDateTime>
  </Head>
  <Body xmlns="http://xml.kishou.go.jp/jmaxml1/body/meteorology1/">
    <Warning type="気象警報・注意報（市町村等）">
      <Item>
        <Kind><Name>レベル３大雨警報</Name><Code>03</Code><Status>解除</Status></Kind>
        <Area><Name>千代田区</Name><Code>1310100</Code></Area>
      </Item>
    </Warning>
  </Body>
</Report>"""],
            "1310100",
            "千代田区",
        )
        snapshot = build_snapshot(observation=None, alerts=alerts)
        entity = BINARY_SENSOR.HaWeatherJmaWarningBinarySensor(
            build_coordinator(snapshot),
            "heavy_rain",
            "warning",
        )

        self.assertFalse(entity.is_on)
        self.assertEqual(entity.extra_state_attributes["status_text"], "解除")

    def test_binary_sensor_is_unknown_when_warning_fetch_failed(self) -> None:
        alerts = PARSER.build_default_alerts(
            warning_area_code="1310100",
            warning_area_name="千代田区",
            report_datetime=None,
            publishing_office=None,
            headline_text=None,
            unavailable=True,
        )
        snapshot = build_snapshot(observation=None, alerts=alerts)
        entity = BINARY_SENSOR.HaWeatherJmaWarningBinarySensor(
            build_coordinator(snapshot),
            "fog",
            "advisory",
        )

        self.assertIsNone(entity.is_on)
        self.assertIsNone(entity.extra_state_attributes["status_text"])

    def test_sensor_platform_skips_location_info_group_when_disabled(self) -> None:
        snapshot = build_snapshot(observation=None)
        location_data = {
            "forecast_area_code": snapshot.location.forecast_area_code,
            "forecast_area_name": snapshot.location.forecast_area_name,
            "forecast_office_code": snapshot.location.forecast_office_code,
            "forecast_office_name": snapshot.location.forecast_office_name,
            "observation_station_code": snapshot.location.observation_station_code,
            "observation_station_name": snapshot.location.observation_station_name,
            "warning_area_code": snapshot.location.warning_area_code,
            "warning_area_name": snapshot.location.warning_area_name,
            "warning_office_code": snapshot.location.warning_office_code,
            "latitude": snapshot.location.latitude,
            "longitude": snapshot.location.longitude,
            "update_interval_minutes": snapshot.location.update_interval_minutes,
            "enabled_warning_levels": list(snapshot.location.enabled_warning_levels),
            "enabled_entity_groups": [
                "forecast_sensors",
                "warning_summary",
                "warning_binary_sensors",
            ],
        }
        filtered_snapshot = PARSER.build_snapshot(
            location=PARSER.build_location_config(
                snapshot.location.entry_id,
                snapshot.location.name,
                location_data,
            ),
            observation=snapshot.observation,
            forecast_days=snapshot.forecast_days,
            forecast_meta=snapshot.forecast_meta,
            alerts=snapshot.alerts,
            alert_summary=snapshot.alert_summary,
            last_api_call_at=snapshot.last_api_call_at,
            last_success_at=snapshot.last_success_at,
            is_partial=snapshot.is_partial,
        )
        coordinator = build_coordinator(filtered_snapshot)
        hass = types.SimpleNamespace(
            data={"ha_weather_jma": {"entry-123": coordinator}},
        )
        added_entities: list[Any] = []

        asyncio.run(
            SENSOR.async_setup_entry(
                hass,
                types.SimpleNamespace(entry_id="entry-123"),
                added_entities.extend,
            )
        )

        entity_ids = {entity.entity_id for entity in added_entities}
        self.assertNotIn(
            "sensor.ha_weather_jma_entry_123_forecast_area",
            entity_ids,
        )

    def test_button_platform_adds_force_refresh_button_when_actions_enabled(self) -> None:
        snapshot = build_snapshot(observation=None)
        coordinator = build_coordinator(snapshot)
        hass = types.SimpleNamespace(
            data={"ha_weather_jma": {"entry-123": coordinator}},
        )
        added_entities: list[Any] = []

        asyncio.run(
            BUTTON.async_setup_entry(
                hass,
                types.SimpleNamespace(entry_id="entry-123"),
                added_entities.extend,
            )
        )

        self.assertEqual(len(added_entities), 1)
        self.assertEqual(
            added_entities[0].entity_id,
            "button.ha_weather_jma_entry_123_force_refresh",
        )

    def test_button_press_requests_coordinator_refresh(self) -> None:
        snapshot = build_snapshot(observation=None)

        class ButtonCoordinator(types.SimpleNamespace):
            def __init__(self) -> None:
                super().__init__(location=snapshot.location, data=snapshot, hass=None)
                self.refresh_calls = 0

            async def async_request_refresh(self) -> None:
                self.refresh_calls += 1

        coordinator = ButtonCoordinator()
        entity = BUTTON.HaWeatherJmaForceRefreshButtonEntity(coordinator)

        asyncio.run(entity.async_press())

        self.assertEqual(coordinator.refresh_calls, 1)

    def test_button_platform_skips_actions_group_when_disabled(self) -> None:
        snapshot = build_snapshot(observation=None)
        disabled_location = build_location(
            [
                "forecast_sensors",
                "warning_summary",
                "warning_binary_sensors",
                "location_info",
            ]
        )
        coordinator = build_coordinator(
            PARSER.build_snapshot(
                location=disabled_location,
                observation=snapshot.observation,
                forecast_days=snapshot.forecast_days,
                forecast_meta=snapshot.forecast_meta,
                alerts=snapshot.alerts,
                alert_summary=snapshot.alert_summary,
                last_api_call_at=snapshot.last_api_call_at,
                last_success_at=snapshot.last_success_at,
                is_partial=snapshot.is_partial,
            )
        )
        hass = types.SimpleNamespace(
            data={"ha_weather_jma": {"entry-123": coordinator}},
        )
        added_entities: list[Any] = []

        asyncio.run(
            BUTTON.async_setup_entry(
                hass,
                types.SimpleNamespace(entry_id="entry-123"),
                added_entities.extend,
            )
        )

        self.assertEqual(added_entities, [])

    def test_binary_sensor_platform_skips_entities_when_group_disabled(self) -> None:
        snapshot = build_snapshot(observation=None)
        location_data = {
            "forecast_area_code": snapshot.location.forecast_area_code,
            "forecast_area_name": snapshot.location.forecast_area_name,
            "forecast_office_code": snapshot.location.forecast_office_code,
            "forecast_office_name": snapshot.location.forecast_office_name,
            "observation_station_code": snapshot.location.observation_station_code,
            "observation_station_name": snapshot.location.observation_station_name,
            "warning_area_code": snapshot.location.warning_area_code,
            "warning_area_name": snapshot.location.warning_area_name,
            "warning_office_code": snapshot.location.warning_office_code,
            "latitude": snapshot.location.latitude,
            "longitude": snapshot.location.longitude,
            "update_interval_minutes": snapshot.location.update_interval_minutes,
            "enabled_warning_levels": list(snapshot.location.enabled_warning_levels),
            "enabled_entity_groups": ["forecast_sensors", "warning_summary"],
        }
        filtered_snapshot = PARSER.build_snapshot(
            location=PARSER.build_location_config(
                snapshot.location.entry_id,
                snapshot.location.name,
                location_data,
            ),
            observation=snapshot.observation,
            forecast_days=snapshot.forecast_days,
            forecast_meta=snapshot.forecast_meta,
            alerts=snapshot.alerts,
            alert_summary=snapshot.alert_summary,
            last_api_call_at=snapshot.last_api_call_at,
            last_success_at=snapshot.last_success_at,
            is_partial=snapshot.is_partial,
        )
        coordinator = build_coordinator(filtered_snapshot)
        hass = types.SimpleNamespace(
            data={"ha_weather_jma": {"entry-123": coordinator}},
        )
        added_entities: list[Any] = []

        asyncio.run(
            BINARY_SENSOR.async_setup_entry(
                hass,
                types.SimpleNamespace(entry_id="entry-123"),
                added_entities.extend,
            )
        )

        self.assertEqual(added_entities, [])


if __name__ == "__main__":
    unittest.main()
