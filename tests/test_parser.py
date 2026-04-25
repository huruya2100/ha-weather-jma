"""Parser regression tests for the ha-weather-jma integration."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_ROOT = ROOT / "custom_components" / "ha_weather_jma"
FIXTURE_ROOT = ROOT / "tests" / "fixtures"


def _load_module(module_name: str):
    spec = importlib.util.spec_from_file_location(
        module_name,
        INTEGRATION_ROOT / f"{module_name.rsplit('.', maxsplit=1)[-1]}.py",
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load module spec for {module_name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_parser_module():
    """Load const.py and parser.py without importing Home Assistant."""
    custom_components = types.ModuleType("custom_components")
    custom_components.__path__ = [str(INTEGRATION_ROOT.parent)]
    sys.modules.setdefault("custom_components", custom_components)

    package = types.ModuleType("custom_components.ha_weather_jma")
    package.__path__ = [str(INTEGRATION_ROOT)]
    sys.modules.setdefault("custom_components.ha_weather_jma", package)

    if "custom_components.ha_weather_jma.const" not in sys.modules:
        _load_module("custom_components.ha_weather_jma.const")
    if "custom_components.ha_weather_jma.parser" not in sys.modules:
        _load_module("custom_components.ha_weather_jma.parser")

    return sys.modules["custom_components.ha_weather_jma.parser"]


PARSER = load_parser_module()


def read_fixture(name: str):
    with (FIXTURE_ROOT / name).open(encoding="utf-8") as fixture_file:
        return json.load(fixture_file)


def read_text_fixture(name: str) -> str:
    return (FIXTURE_ROOT / name).read_text(encoding="utf-8")


class ParserTests(unittest.TestCase):
    """Parser-focused regression tests."""

    def test_warning_constants_only_include_existing_jma_combinations(self) -> None:
        const = sys.modules["custom_components.ha_weather_jma.const"]

        self.assertIn(("thunder", "advisory"), const.WARNING_ENTITY_TITLES)
        self.assertIn(("landslide", "warning"), const.WARNING_ENTITY_TITLES)
        self.assertIn(("landslide", "danger_warning"), const.WARNING_ENTITY_TITLES)
        self.assertNotIn(("thunder", "warning"), const.WARNING_ENTITY_TITLES)
        self.assertNotIn(("flood", "emergency_warning"), const.WARNING_ENTITY_TITLES)
        self.assertNotIn("27", const.WARNING_CODE_MAP)
        self.assertIn("09", const.WARNING_CODE_MAP)
        self.assertIn("39", const.WARNING_CODE_MAP)
        self.assertIn("43", const.WARNING_CODE_MAP)
        self.assertIn("48", const.WARNING_CODE_MAP)
        self.assertIn("49", const.WARNING_CODE_MAP)

    def test_build_candidates_from_minimal_definitions(self) -> None:
        area_data = read_fixture("area_minimal.json")
        station_data = read_fixture("amedastable_minimal.json")

        region_candidates = PARSER.build_region_candidates(area_data)
        forecast_candidates = PARSER.build_forecast_area_candidates(area_data)
        warning_candidates = PARSER.build_warning_area_candidates(area_data)
        station_candidates = PARSER.build_observation_station_candidates(station_data)

        self.assertEqual(region_candidates["010300"].name, "関東甲信")
        self.assertEqual(forecast_candidates["130010"].office_code, "130000")
        self.assertEqual(forecast_candidates["130010"].office_name, "気象庁")
        self.assertEqual(warning_candidates["1310100"].office_code, "130000")
        self.assertEqual(station_candidates["44132"].name, "東京")
        self.assertAlmostEqual(
            station_candidates["44132"].latitude, 35.6916666667, places=6
        )
        self.assertAlmostEqual(station_candidates["44132"].longitude, 139.75, places=6)

    def test_parse_observation_normalizes_measurements(self) -> None:
        observation = PARSER.parse_observation(
            read_fixture("amedas_observation_normal.json"),
            "2026-04-14T20:40:00+09:00",
        )

        self.assertAlmostEqual(observation.temperature_c, 18.1)
        self.assertEqual(observation.humidity_percent, 77)
        self.assertAlmostEqual(observation.wind_speed_ms, 3.0)
        self.assertEqual(observation.wind_direction_deg, 135)
        self.assertAlmostEqual(observation.pressure_hpa, 1013.8)
        self.assertEqual(observation.condition_code, "100")
        self.assertEqual(observation.condition_text, "晴れ")

    def test_parse_observation_missing_fields_and_invalid_wind_direction(self) -> None:
        observation = PARSER.parse_observation(
            read_fixture("observation_missing_fields.json"),
            "2026-04-14T20:40:00+09:00",
        )

        self.assertIsNone(observation.temperature_c)
        self.assertIsNone(observation.humidity_percent)
        self.assertIsNone(observation.wind_speed_ms)
        self.assertIsNone(observation.wind_direction_deg)
        self.assertIsNone(observation.pressure_hpa)
        self.assertIsNone(observation.condition_code)
        self.assertIsNone(observation.condition_text)

    def test_forecast_supports_observation_station_checks_temperature_area(
        self,
    ) -> None:
        forecast_data = read_fixture("forecast_normal.json")

        self.assertTrue(
            PARSER.forecast_supports_observation_station(
                forecast_data,
                "44132",
            )
        )
        self.assertFalse(
            PARSER.forecast_supports_observation_station(
                forecast_data,
                "99999",
            )
        )

    def test_extract_forecast_observation_station_codes(self) -> None:
        forecast_data = read_fixture("forecast_normal.json")

        self.assertEqual(
            PARSER.extract_forecast_observation_station_codes(forecast_data),
            ("44132",),
        )

    def test_resolve_weather_condition_prefers_observation_when_present(self) -> None:
        observation = PARSER.parse_observation(
            read_fixture("amedas_observation_normal.json"),
            "2026-04-14T20:40:00+09:00",
        )
        forecast_days = PARSER.parse_forecast(
            read_fixture("forecast_normal.json"),
            "130010",
            "44132",
        )

        condition, raw_text = PARSER.resolve_weather_condition(
            observation, forecast_days
        )

        self.assertEqual(condition, "sunny")
        self.assertEqual(raw_text, "晴れ")

    def test_parse_forecast_merges_short_and_weekly_series(self) -> None:
        forecast_days = PARSER.parse_forecast(
            read_fixture("forecast_normal.json"),
            "130010",
            "44132",
        )

        self.assertEqual(len(forecast_days), 3)
        self.assertEqual(forecast_days[0].target_date.isoformat(), "2026-04-14")
        self.assertEqual(forecast_days[0].precip_probability_percent, 20)
        self.assertEqual(forecast_days[1].temp_min_c, 14.0)
        self.assertEqual(forecast_days[1].temp_max_c, 21.0)
        self.assertEqual(forecast_days[1].precip_probability_percent, 50)
        self.assertEqual(forecast_days[2].temp_min_c, 12.0)
        self.assertEqual(forecast_days[2].temp_max_c, 23.0)
        self.assertEqual(forecast_days[2].precip_probability_percent, 50)

    def test_parse_forecast_tolerates_missing_wind_text(self) -> None:
        forecast_data = read_fixture("forecast_normal.json")
        forecast_data[0]["timeSeries"][0]["areas"][0].pop("winds", None)

        forecast_days = PARSER.parse_forecast(
            forecast_data,
            "130010",
            "44132",
        )

        self.assertEqual(len(forecast_days), 3)
        self.assertIsNone(forecast_days[0].wind_text)
        self.assertEqual(forecast_days[1].temp_max_c, 21.0)

    def test_parse_forecast_handles_missing_fields_empty_pop_and_negative_temp(
        self,
    ) -> None:
        forecast_days = PARSER.parse_forecast(
            read_fixture("forecast_missing_fields.json"),
            "130010",
            "44132",
        )

        self.assertEqual(len(forecast_days), 1)
        self.assertEqual(forecast_days[0].target_date.isoformat(), "2026-01-10")
        self.assertIsNone(forecast_days[0].precip_probability_percent)
        self.assertAlmostEqual(forecast_days[0].temp_min_c, -2.0)
        self.assertIsNone(forecast_days[0].temp_max_c)
        self.assertIsNone(forecast_days[0].wind_text)

    def test_parse_alerts_builds_active_summary(self) -> None:
        alerts = PARSER.parse_alerts_xml(
            [read_text_fixture("warning_xml_current.xml")],
            "1310100",
            "千代田区",
        )
        summary = PARSER.build_alert_summary(alerts)

        self.assertTrue(alerts[("fog", "advisory")].is_active)
        self.assertFalse(alerts[("high_wave", "advisory")].is_active)
        self.assertEqual(summary.max_level, "advisory")
        self.assertEqual(summary.active_titles, ("レベル２濃霧注意報",))

    def test_parse_alerts_with_multiple_active_warnings_prioritizes_highest_level(
        self,
    ) -> None:
        alerts = PARSER.parse_alerts_xml(
            [
                read_text_fixture("warning_xml_current.xml"),
                read_text_fixture("warning_xml_heavyrain_level4.xml"),
                read_text_fixture("warning_xml_landslide_level4.xml"),
            ],
            "1310100",
            "千代田区",
        )
        summary = PARSER.build_alert_summary(alerts)

        self.assertTrue(alerts[("heavy_rain", "danger_warning")].is_active)
        self.assertTrue(alerts[("landslide", "danger_warning")].is_active)
        self.assertTrue(alerts[("fog", "advisory")].is_active)
        self.assertEqual(summary.max_level, "danger_warning")
        self.assertCountEqual(
            summary.active_titles,
            (
                "レベル４大雨危険警報",
                "レベル４土砂災害危険警報",
                "レベル２濃霧注意報",
            ),
        )

    def test_parse_alerts_supports_danger_warning_codes_and_transition_statuses(
        self,
    ) -> None:
        alerts = PARSER.parse_alerts_xml(
            [read_text_fixture("warning_xml_landslide_level4.xml")],
            "1310100",
            "千代田区",
        )
        summary = PARSER.build_alert_summary(alerts)

        self.assertTrue(alerts[("landslide", "danger_warning")].is_active)
        self.assertEqual(summary.max_level, "danger_warning")
        self.assertEqual(
            summary.active_titles,
            ("レベル４土砂災害危険警報",),
        )

    def test_parse_alerts_when_all_warnings_cleared_returns_none_summary(self) -> None:
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
        <Kind><Name>濃霧注意報</Name><Code>20</Code><Status>解除</Status></Kind>
        <Area><Name>千代田区</Name><Code>1310100</Code></Area>
      </Item>
    </Warning>
  </Body>
</Report>"""],
            "1310100",
            "千代田区",
        )
        summary = PARSER.build_alert_summary(alerts)

        self.assertFalse(any(item.is_active for item in alerts.values()))
        self.assertEqual(summary.max_level, "none")
        self.assertEqual(summary.active_titles, ())

    def test_unknown_warning_code_is_ignored_with_warning_log(self) -> None:
        with self.assertLogs(
            "custom_components.ha_weather_jma.parser", level="WARNING"
        ) as captured:
            alerts = PARSER.parse_alerts_xml(
                ["""<?xml version="1.0" encoding="UTF-8"?>
<Report xmlns="http://xml.kishou.go.jp/jmaxml1/">
  <Control><PublishingOffice>気象庁</PublishingOffice></Control>
  <Head xmlns="http://xml.kishou.go.jp/jmaxml1/informationBasis1/">
    <ReportDateTime>2026-05-29T01:15:00+09:00</ReportDateTime>
  </Head>
  <Body xmlns="http://xml.kishou.go.jp/jmaxml1/body/meteorology1/">
    <Warning type="気象警報・注意報（市町村等）">
      <Item>
        <Kind><Name>未知の警報</Name><Code>99</Code><Status>発表</Status></Kind>
        <Area><Name>千代田区</Name><Code>1310100</Code></Area>
      </Item>
    </Warning>
  </Body>
</Report>"""],
                "1310100",
                "千代田区",
            )

        self.assertTrue(
            any("unknown JMA warning code" in message for message in captured.output)
        )
        self.assertFalse(any(item.is_active for item in alerts.values()))
        summary = PARSER.build_alert_summary(alerts)
        self.assertEqual(summary.max_level, "none")

    def test_build_location_config_falls_back_to_entry_id_slug(self) -> None:
        location = PARSER.build_location_config(
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
                "enabled_warning_levels": ["advisory", "warning"],
            },
        )

        self.assertEqual(location.entry_slug, "entry_123")
        self.assertEqual(location.enabled_warning_levels, ("advisory", "warning"))

    def test_build_location_config_defaults_entity_groups_for_legacy_entries(
        self,
    ) -> None:
        location = PARSER.build_location_config(
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
                "enabled_warning_levels": ["advisory", "warning"],
            },
        )

        self.assertEqual(
            location.enabled_entity_groups,
            (
                "weather_forecast",
                "warnings",
                "management",
            ),
        )

    def test_build_location_config_maps_legacy_entity_groups(self) -> None:
        location = PARSER.build_location_config(
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
                "enabled_warning_levels": ["advisory", "warning"],
                "enabled_entity_groups": [
                    "forecast_sensors",
                    "warning_summary",
                    "warning_binary_sensors",
                    "location_info",
                    "actions",
                ],
            },
        )

        self.assertEqual(
            location.enabled_entity_groups,
            (
                "weather_forecast",
                "warnings",
                "management",
            ),
        )


if __name__ == "__main__":
    unittest.main()
