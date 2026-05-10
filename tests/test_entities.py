"""Entity behavior regression tests."""

from __future__ import annotations

import asyncio
import types
import unittest
from typing import Any

from tests.support import load_modules, read_fixture, read_text_fixture

LOADED = load_modules(
    "binary_sensor",
    "button",
    "sensor",
    "weather",
    "parser",
)
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
                "weather_forecast",
                "warnings",
                "management",
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
        self.assertEqual(len(forecast), 2)
        self.assertEqual(forecast[0]["condition"], "rainy")
        self.assertEqual(forecast[0]["native_temperature"], 21.0)
        self.assertEqual(forecast[0]["native_templow"], 14.0)

    def test_weather_forecast_does_not_fill_missing_forecast_temperature_from_observation(
        self,
    ) -> None:
        forecast_payload = read_fixture("forecast_normal.json")
        forecast_payload[1]["timeSeries"][1]["areas"][0]["area"] = {
            "name": "石垣島",
            "code": "94081",
        }
        location = build_location()
        forecast_days = PARSER.parse_forecast(forecast_payload, "130010", "94017")
        alerts = PARSER.parse_alerts_xml(
            [read_text_fixture("warning_xml_current.xml")],
            "1310100",
            "千代田区",
        )
        snapshot = PARSER.build_snapshot(
            location=location,
            observation=PARSER.parse_observation(
                read_fixture("amedas_observation_normal.json"),
                "2026-04-14T20:40:00+09:00",
            ),
            forecast_days=forecast_days,
            forecast_meta=PARSER.parse_forecast_metadata(forecast_payload),
            alerts=alerts,
            alert_summary=PARSER.build_alert_summary(alerts),
            last_api_call_at=None,
            last_success_at=None,
            is_partial=False,
        )
        entity = WEATHER.HaWeatherJmaEntity(build_coordinator(snapshot))

        forecast = asyncio.run(entity.async_forecast_daily())

        self.assertEqual(entity.native_temperature, 18.1)
        self.assertEqual(forecast, [])

    def test_weather_forecast_does_not_use_low_temperature_as_high_temperature(
        self,
    ) -> None:
        forecast_payload = read_fixture("forecast_normal.json")
        forecast_payload[1]["timeSeries"][1]["areas"][0]["tempsMax"][1] = ""
        snapshot = build_snapshot(observation=None)
        forecast_days = PARSER.parse_forecast(forecast_payload, "130010", "44132")
        entity = WEATHER.HaWeatherJmaEntity(
            build_coordinator(
                PARSER.build_snapshot(
                    location=snapshot.location,
                    observation=snapshot.observation,
                    forecast_days=forecast_days,
                    forecast_meta=snapshot.forecast_meta,
                    alerts=snapshot.alerts,
                    alert_summary=snapshot.alert_summary,
                    last_api_call_at=snapshot.last_api_call_at,
                    last_success_at=snapshot.last_success_at,
                    is_partial=snapshot.is_partial,
                )
            )
        )

        forecast = asyncio.run(entity.async_forecast_daily())

        self.assertEqual(len(forecast), 1)
        self.assertEqual(forecast[0]["native_temperature"], 21.0)
        self.assertEqual(forecast[0]["native_templow"], 14.0)

    def test_weather_coordinator_update_notifies_daily_forecast_listeners(self) -> None:
        snapshot = build_snapshot(observation=None)

        class WeatherEntity(WEATHER.HaWeatherJmaEntity):
            def __init__(self) -> None:
                super().__init__(build_coordinator(snapshot))
                self.updated_forecast_types = None

            def async_update_listeners(self, forecast_types):
                self.updated_forecast_types = forecast_types

                async def _done():
                    return None

                return _done()

        entity = WeatherEntity()
        entity.hass = types.SimpleNamespace(async_create_task=lambda coro: coro.close())

        entity._handle_coordinator_update()

        self.assertEqual(entity.updated_forecast_types, ("daily",))

    def test_weather_platform_skips_entity_when_forecast_group_disabled(self) -> None:
        snapshot = build_snapshot(observation=None)
        disabled_location = build_location(["warnings", "management"])
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
            WEATHER.async_setup_entry(
                hass,
                types.SimpleNamespace(entry_id="entry-123"),
                added_entities.extend,
            )
        )

        self.assertEqual(added_entities, [])

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

    def test_report_datetime_sensor_exposes_forecast_coverage_metadata(self) -> None:
        snapshot = build_snapshot(observation=None)
        description = next(
            item for item in SENSOR.DESCRIPTIONS if item.key == "report_datetime"
        )
        entity = SENSOR.HaWeatherJmaSensorEntity(
            build_coordinator(snapshot),
            description,
        )

        attrs = entity.extra_state_attributes

        self.assertEqual(attrs["forecast_area_code"], "130010")
        self.assertEqual(attrs["observation_station_code"], "44132")
        self.assertIn("representative area", attrs["weekly_weather_area_policy"])
        self.assertIn(
            "Representative stations are not substituted",
            attrs["weekly_temperature_station_policy"],
        )
        self.assertEqual(
            attrs["daily_forecast_coverage"][0]["weather_area_code"],
            "130010",
        )
        self.assertEqual(
            attrs["daily_forecast_coverage"][1]["temperature_station_code"],
            "44132",
        )

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

    def test_entity_device_info_registers_as_normal_device(self) -> None:
        snapshot = build_snapshot(observation=None)
        entity = WEATHER.HaWeatherJmaEntity(build_coordinator(snapshot))

        self.assertEqual(
            entity._attr_device_info["identifiers"], {("ha_weather_jma", "entry-123")}
        )
        self.assertEqual(entity._attr_device_info["name"], "東京")
        self.assertNotIn("entry_type", entity._attr_device_info)

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

    def test_force_refresh_button_reports_refresh_timestamps(self) -> None:
        snapshot = build_snapshot(observation=None)
        entity = BUTTON.HaWeatherJmaForceRefreshButtonEntity(
            build_coordinator(snapshot)
        )

        self.assertEqual(
            entity.extra_state_attributes["forecast_area_name"],
            snapshot.location.forecast_area_name,
        )
        self.assertEqual(
            entity.extra_state_attributes["forecast_area_code"],
            snapshot.location.forecast_area_code,
        )
        self.assertEqual(
            entity.extra_state_attributes["observation_station_name"],
            snapshot.location.observation_station_name,
        )
        self.assertEqual(
            entity.extra_state_attributes["observation_station_code"],
            snapshot.location.observation_station_code,
        )
        self.assertEqual(
            entity.extra_state_attributes["warning_area_name"],
            snapshot.location.warning_area_name,
        )
        self.assertEqual(
            entity.extra_state_attributes["warning_area_code"],
            snapshot.location.warning_area_code,
        )
        self.assertEqual(
            entity.extra_state_attributes["update_interval_minutes"],
            snapshot.location.update_interval_minutes,
        )
        self.assertEqual(
            entity.extra_state_attributes["last_api_call_at"],
            snapshot.last_api_call_at,
        )
        self.assertEqual(
            entity.extra_state_attributes["last_success_at"],
            snapshot.last_success_at,
        )

    def test_sensor_platform_adds_management_timestamps_when_enabled(
        self,
    ) -> None:
        snapshot = build_snapshot(observation=None)
        coordinator = build_coordinator(snapshot)
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

        values_by_entity_id = {
            entity.entity_id: entity.native_value for entity in added_entities
        }
        self.assertEqual(
            values_by_entity_id[
                "sensor.ha_weather_jma_entry_123_last_api_call_at"
            ],
            snapshot.last_api_call_at,
        )
        self.assertEqual(
            values_by_entity_id[
                "sensor.ha_weather_jma_entry_123_last_success_at"
            ],
            snapshot.last_success_at,
        )

    def test_sensor_platform_skips_management_timestamps_when_disabled(self) -> None:
        snapshot = build_snapshot(observation=None)
        disabled_location = build_location(
            [
                "weather_forecast",
                "warnings",
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
            SENSOR.async_setup_entry(
                hass,
                types.SimpleNamespace(entry_id="entry-123"),
                added_entities.extend,
            )
        )

        entity_ids = {entity.entity_id for entity in added_entities}
        self.assertNotIn(
            "sensor.ha_weather_jma_entry_123_last_api_call_at", entity_ids
        )
        self.assertNotIn(
            "sensor.ha_weather_jma_entry_123_last_success_at", entity_ids
        )

    def test_sensor_platform_adds_read_only_location_metadata_when_management_enabled(
        self,
    ) -> None:
        snapshot = build_snapshot(observation=None)
        coordinator = build_coordinator(snapshot)
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

        values_by_entity_id = {
            entity.entity_id: entity.native_value for entity in added_entities
        }
        self.assertEqual(
            values_by_entity_id,
            {
                "sensor.ha_weather_jma_entry_123_report_datetime": (
                    snapshot.forecast_meta.report_datetime
                ),
                "sensor.ha_weather_jma_entry_123_publishing_office": (
                    snapshot.forecast_meta.publishing_office
                ),
                "sensor.ha_weather_jma_entry_123_today_precip_probability": 20,
                "sensor.ha_weather_jma_entry_123_tomorrow_precip_probability": 50,
                "sensor.ha_weather_jma_entry_123_alert_summary": "レベル２濃霧注意報",
                "sensor.ha_weather_jma_entry_123_alert_max_level": "advisory",
                "sensor.ha_weather_jma_entry_123_forecast_area": (
                    snapshot.location.forecast_area_name
                ),
                "sensor.ha_weather_jma_entry_123_observation_station": (
                    snapshot.location.observation_station_name
                ),
                "sensor.ha_weather_jma_entry_123_warning_area": (
                    snapshot.location.warning_area_name
                ),
                "sensor.ha_weather_jma_entry_123_last_api_call_at": (
                    snapshot.last_api_call_at
                ),
                "sensor.ha_weather_jma_entry_123_last_success_at": (
                    snapshot.last_success_at
                ),
            },
        )

        forecast_area = next(
            entity
            for entity in added_entities
            if entity.entity_id == "sensor.ha_weather_jma_entry_123_forecast_area"
        )
        self.assertEqual(
            forecast_area.extra_state_attributes["area_code"],
            snapshot.location.forecast_area_code,
        )
        self.assertIn(
            "representative area",
            forecast_area.extra_state_attributes["weekly_weather_area_policy"],
        )

    def test_sensor_platform_skips_location_metadata_when_management_group_disabled(
        self,
    ) -> None:
        snapshot = build_snapshot(observation=None)
        disabled_location = build_location(
            [
                "weather_forecast",
                "warnings",
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
        self.assertNotIn(
            "sensor.ha_weather_jma_entry_123_observation_station",
            entity_ids,
        )
        self.assertNotIn(
            "sensor.ha_weather_jma_entry_123_warning_area",
            entity_ids,
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

    def test_sensor_platform_skips_management_group_when_disabled(self) -> None:
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
                "weather_forecast",
                "warnings",
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

    def test_button_platform_adds_force_refresh_button_when_management_enabled(
        self,
    ) -> None:
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

    def test_button_platform_skips_management_group_when_disabled(self) -> None:
        snapshot = build_snapshot(observation=None)
        disabled_location = build_location(
            [
                "weather_forecast",
                "warnings",
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
            "enabled_entity_groups": ["weather_forecast"],
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
