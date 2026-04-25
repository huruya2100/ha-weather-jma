"""Config flow regression tests."""

from __future__ import annotations

import asyncio
import unittest

from tests.support import get_stub_module, load_modules, read_fixture

LOADED = load_modules("config_flow")
CONFIG_FLOW = LOADED["config_flow"]
CONFIG_ENTRIES = get_stub_module("homeassistant.config_entries")
HA_CORE = get_stub_module("homeassistant.core")


class FakeApiClient:
    """Config flow API stub."""

    def __init__(self, *, area_data, station_data, forecast_data) -> None:
        self.area_data = area_data
        self.station_data = station_data
        self.forecast_data = forecast_data

    async def fetch_area_definitions(self):
        return self.area_data

    async def fetch_amedas_table(self):
        return self.station_data

    async def fetch_forecast(self, office_code: str):
        del office_code
        return self.forecast_data


class ConfigFlowTests(unittest.TestCase):
    """Integration-style config flow tests."""

    def setUp(self) -> None:
        CONFIG_ENTRIES.ConfigFlow._configured_unique_ids.clear()
        self.flow = CONFIG_FLOW.HaWeatherJmaConfigFlow()
        self.flow.hass = HA_CORE.HomeAssistant()
        self.flow._api_client = FakeApiClient(
            area_data=read_fixture("area_minimal.json"),
            station_data=read_fixture("amedastable_minimal.json"),
            forecast_data=read_fixture("forecast_normal.json"),
        )

    def _schema_field_names(self, schema) -> set[str]:
        return {field.schema for field in schema.schema}

    def _schema_options(self, schema, field_name: str) -> dict[str, str]:
        for field, validator in schema.schema.items():
            if field.schema == field_name:
                return dict(validator.container)
        raise AssertionError(f"Field {field_name} not found")

    def _schema_default(self, schema, field_name: str):
        for field in schema.schema:
            if field.schema == field_name:
                return field.default()
        raise AssertionError(f"Field {field_name} not found")

    def test_config_flow_allows_selection_steps_and_creates_entry(self) -> None:
        result = asyncio.run(self.flow.async_step_user({"region_code": "010300"}))
        self.assertEqual(result["step_id"], "forecast_area")

        result = asyncio.run(
            self.flow.async_step_forecast_area({"forecast_area_code": "130010"})
        )
        self.assertEqual(result["step_id"], "observation")

        result = asyncio.run(
            self.flow.async_step_observation({"observation_station_code": "44132"})
        )
        self.assertEqual(result["step_id"], "warning")

        result = asyncio.run(
            self.flow.async_step_warning({"warning_area_code": "1310100"})
        )
        self.assertEqual(result["step_id"], "options")

        result = asyncio.run(
            self.flow.async_step_options(
                {
                    "name": "東京",
                    "update_interval_minutes": 15,
                    "enabled_warning_levels": ["advisory", "warning"],
                    "enabled_entity_groups": [
                        "forecast_sensors",
                        "warning_summary",
                        "warning_binary_sensors",
                    ],
                }
            )
        )

        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["title"], "東京")
        self.assertEqual(result["data"]["forecast_area_code"], "130010")
        self.assertEqual(result["data"]["observation_station_code"], "44132")
        self.assertEqual(result["data"]["warning_area_code"], "1310100")
        self.assertEqual(
            result["data"]["enabled_warning_levels"], ["advisory", "warning"]
        )
        self.assertEqual(
            result["data"]["enabled_entity_groups"],
            ["forecast_sensors", "warning_summary", "warning_binary_sensors"],
        )

    def test_options_step_includes_entity_group_selection(self) -> None:
        self.flow._entry_data = {
            "forecast_area_name": "東京地方",
        }

        result = asyncio.run(self.flow.async_step_options())

        self.assertEqual(result["type"], "form")
        self.assertEqual(
            self._schema_field_names(result["data_schema"]),
            {
                "name",
                "update_interval_minutes",
                "enabled_warning_levels",
                "enabled_entity_groups",
            },
        )

    def test_options_step_defaults_to_recommended_entity_groups(self) -> None:
        self.flow._entry_data = {
            "forecast_area_name": "東京地方",
        }

        result = asyncio.run(self.flow.async_step_options())

        self.assertEqual(
            self._schema_default(result["data_schema"], "enabled_entity_groups"),
            [
                "forecast_sensors",
                "warning_summary",
                "warning_binary_sensors",
                "actions",
            ],
        )

    def test_config_flow_allows_disabling_warning_binary_sensors_and_levels(
        self,
    ) -> None:
        self.flow._entry_data = {
            "forecast_area_code": "130010",
            "observation_station_code": "44132",
            "warning_area_code": "1310100",
        }

        result = asyncio.run(
            self.flow.async_step_options(
                {
                    "name": "東京",
                    "update_interval_minutes": 10,
                    "enabled_warning_levels": [],
                    "enabled_entity_groups": ["forecast_sensors"],
                }
            )
        )

        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"]["enabled_warning_levels"], [])

    def test_config_flow_allows_nearby_observation_station_for_selected_forecast_area(
        self,
    ) -> None:
        self.flow._api_client = FakeApiClient(
            area_data=read_fixture("area_minimal.json"),
            station_data={
                **read_fixture("amedastable_minimal.json"),
                "44133": {
                    "kjName": "近隣観測所",
                    "lat": [35, 42.0],
                    "lon": [139, 46.0],
                },
                "99999": {
                    "kjName": "遠方観測所",
                    "lat": [34, 0],
                    "lon": [135, 0],
                },
            },
            forecast_data=read_fixture("forecast_normal.json"),
        )
        asyncio.run(self.flow.async_step_user({"region_code": "010300"}))
        asyncio.run(
            self.flow.async_step_forecast_area({"forecast_area_code": "130010"})
        )

        result = asyncio.run(
            self.flow.async_step_observation({"observation_station_query": ""})
        )
        options = self._schema_options(
            result["data_schema"],
            "observation_station_code",
        )
        self.assertIn("44132", options)
        self.assertIn("44133", options)
        self.assertNotIn("99999", options)

        result = asyncio.run(
            self.flow.async_step_observation({"observation_station_code": "44133"})
        )
        self.assertEqual(result["step_id"], "warning")

    def test_config_flow_rejects_far_observation_station_outside_candidate_set(
        self,
    ) -> None:
        self.flow._api_client = FakeApiClient(
            area_data=read_fixture("area_minimal.json"),
            station_data={
                **read_fixture("amedastable_minimal.json"),
                "99999": {
                    "kjName": "遠方観測所",
                    "lat": [34, 0],
                    "lon": [135, 0],
                },
            },
            forecast_data=read_fixture("forecast_normal.json"),
        )
        asyncio.run(self.flow.async_step_user({"region_code": "010300"}))
        asyncio.run(
            self.flow.async_step_forecast_area({"forecast_area_code": "130010"})
        )

        result = asyncio.run(
            self.flow.async_step_observation({"observation_station_code": "99999"})
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["errors"]["base"], "invalid_selection")

    def test_config_flow_rejects_duplicate_entry(self) -> None:
        self.flow._entry_data = {
            "forecast_area_code": "130010",
            "observation_station_code": "44132",
            "warning_area_code": "1310100",
        }
        CONFIG_ENTRIES.ConfigFlow._configured_unique_ids.add("130010:44132:1310100")

        with self.assertRaises(CONFIG_ENTRIES.AbortFlow):
            asyncio.run(
                self.flow.async_step_options(
                    {
                        "name": "東京",
                        "update_interval_minutes": 10,
                        "enabled_warning_levels": ["advisory", "warning"],
                        "enabled_entity_groups": [
                            "forecast_sensors",
                            "warning_summary",
                            "warning_binary_sensors",
                        ],
                    }
                )
            )

    def test_observation_step_limits_large_global_candidate_set(
        self,
    ) -> None:
        large_station_data = {
            f"{44000 + index}": {
                "kjName": f"観測所{index}",
                "lat": [35, 42.0],
                "lon": [139, 46.0],
            }
            for index in range(CONFIG_FLOW.MAX_FILTERED_CANDIDATES + 1)
        }
        large_station_data["44132"] = read_fixture("amedastable_minimal.json")["44132"]

        self.flow._api_client = FakeApiClient(
            area_data=read_fixture("area_minimal.json"),
            station_data=large_station_data,
            forecast_data=read_fixture("forecast_normal.json"),
        )
        asyncio.run(self.flow.async_step_user({"region_code": "010300"}))
        asyncio.run(
            self.flow.async_step_forecast_area({"forecast_area_code": "130010"})
        )

        result = asyncio.run(self.flow.async_step_observation())
        self.assertEqual(result["type"], "form")
        self.assertEqual(
            self._schema_field_names(result["data_schema"]),
            {"observation_station_query", "observation_station_code"},
        )
        options = self._schema_options(
            result["data_schema"],
            "observation_station_code",
        )
        self.assertLessEqual(
            len(options),
            1 + CONFIG_FLOW.MAX_NEARBY_OBSERVATION_CANDIDATES,
        )
        self.assertIn("44132", options)

        result = asyncio.run(
            self.flow.async_step_observation({"observation_station_query": "東京"})
        )
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["errors"], {})
        self.assertEqual(
            self._schema_field_names(result["data_schema"]),
            {"observation_station_query", "observation_station_code"},
        )

    def test_user_step_lists_regions_before_forecast_areas(self) -> None:
        result = asyncio.run(self.flow.async_step_user())

        self.assertEqual(result["type"], "form")
        self.assertEqual(
            self._schema_field_names(result["data_schema"]),
            {"region_query", "region_code"},
        )
        options = self._schema_options(result["data_schema"], "region_code")
        self.assertIn("010300", options)

    def test_forecast_area_step_is_filtered_by_selected_region(self) -> None:
        self.flow._api_client = FakeApiClient(
            area_data={
                "centers": {
                    "010300": {"name": "関東甲信", "children": ["130000"]},
                    "020300": {"name": "四国", "children": ["360000"]},
                },
                "offices": {
                    "130000": {
                        "name": "東京都",
                        "officeName": "気象庁",
                        "parent": "010300",
                        "children": ["130010"],
                    },
                    "360000": {
                        "name": "徳島県",
                        "officeName": "徳島地方気象台",
                        "parent": "020300",
                        "children": ["360010"],
                    },
                },
                "class10s": {
                    "130010": {
                        "name": "東京地方",
                        "parent": "130000",
                        "children": [],
                    },
                    "360010": {
                        "name": "徳島県",
                        "parent": "360000",
                        "children": [],
                    },
                },
                "class15s": {},
                "class20s": {},
            },
            station_data=read_fixture("amedastable_minimal.json"),
            forecast_data=read_fixture("forecast_normal.json"),
        )

        result = asyncio.run(self.flow.async_step_user({"region_code": "010300"}))

        self.assertEqual(result["step_id"], "forecast_area")
        options = self._schema_options(result["data_schema"], "forecast_area_code")
        self.assertIn("130010", options)
        self.assertNotIn("360010", options)

    def test_warning_step_is_filtered_by_selected_forecast_office(self) -> None:
        remote_class20s = {
            f"360{index:04d}": {
                "name": f"徳島地域{index}",
                "parent": "360011",
            }
            for index in range(CONFIG_FLOW.MAX_FILTERED_CANDIDATES + 1)
        }
        self.flow._api_client = FakeApiClient(
            area_data={
                "centers": {
                    "010300": {"name": "関東甲信", "children": ["130000"]},
                    "020300": {"name": "四国", "children": ["360000"]},
                },
                "offices": {
                    "130000": {
                        "name": "東京都",
                        "officeName": "気象庁",
                        "parent": "010300",
                        "children": ["130010"],
                    },
                    "360000": {
                        "name": "徳島県",
                        "officeName": "徳島地方気象台",
                        "parent": "020300",
                        "children": ["360010"],
                    },
                },
                "class10s": {
                    "130010": {
                        "name": "東京地方",
                        "parent": "130000",
                        "children": ["130011"],
                    },
                    "360010": {
                        "name": "徳島県",
                        "parent": "360000",
                        "children": ["360011"],
                    },
                },
                "class15s": {
                    "130011": {
                        "name": "２３区西部",
                        "parent": "130010",
                        "children": ["1310100", "1310200"],
                    },
                    "360011": {
                        "name": "徳島地域",
                        "parent": "360010",
                        "children": list(remote_class20s),
                    },
                },
                "class20s": {
                    "1310100": {"name": "千代田区", "parent": "130011"},
                    "1310200": {"name": "中央区", "parent": "130011"},
                    **remote_class20s,
                },
            },
            station_data=read_fixture("amedastable_minimal.json"),
            forecast_data=read_fixture("forecast_normal.json"),
        )

        asyncio.run(self.flow.async_step_user({"region_code": "010300"}))
        asyncio.run(
            self.flow.async_step_forecast_area({"forecast_area_code": "130010"})
        )
        asyncio.run(
            self.flow.async_step_observation({"observation_station_code": "44132"})
        )

        result = asyncio.run(self.flow.async_step_warning())

        self.assertEqual(result["type"], "form")
        self.assertEqual(
            self._schema_field_names(result["data_schema"]),
            {"warning_area_query", "warning_area_code"},
        )
        options = self._schema_options(result["data_schema"], "warning_area_code")
        self.assertEqual(set(options), {"1310100", "1310200"})


if __name__ == "__main__":
    unittest.main()
