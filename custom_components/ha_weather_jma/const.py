"""Constants for the ha-weather-jma integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "ha_weather_jma"

ATTRIBUTION: Final = (
    "Unofficial integration using data published by the Japan Meteorological Agency"
)
MANUFACTURER: Final = "Home Assistant custom integration"
MODEL: Final = "ha-weather-jma"

AREA_URL: Final = "https://www.jma.go.jp/bosai/common/const/area.json"
AMEDAS_TABLE_URL: Final = "https://www.jma.go.jp/bosai/amedas/const/amedastable.json"
AMEDAS_LATEST_TIME_URL: Final = (
    "https://www.jma.go.jp/bosai/amedas/data/latest_time.txt"
)
AMEDAS_MAP_URL: Final = "https://www.jma.go.jp/bosai/amedas/data/map/{timestamp}.json"
FORECAST_URL: Final = (
    "https://www.jma.go.jp/bosai/forecast/data/forecast/{office_code}.json"
)
WARNING_XML_FEED_SHORT_URL: Final = (
    "https://www.data.jma.go.jp/developer/xml/feed/extra.xml"
)
WARNING_XML_FEED_LONG_URL: Final = (
    "https://www.data.jma.go.jp/developer/xml/feed/extra_l.xml"
)

DEFAULT_UPDATE_INTERVAL_MINUTES: Final = 10
MIN_UPDATE_INTERVAL_MINUTES: Final = 5
MAX_UPDATE_INTERVAL_MINUTES: Final = 60
HTTP_TIMEOUT_SECONDS: Final = 10
HTTP_RETRY_COUNT: Final = 1
HTTP_RETRY_BACKOFF_BASE_SECONDS: Final = 1
DEFINITION_CACHE_TTL_SECONDS: Final = 24 * 60 * 60

CONF_FORECAST_AREA_CODE: Final = "forecast_area_code"
CONF_FORECAST_AREA_NAME: Final = "forecast_area_name"
CONF_FORECAST_OFFICE_CODE: Final = "forecast_office_code"
CONF_FORECAST_OFFICE_NAME: Final = "forecast_office_name"
CONF_OBSERVATION_STATION_CODE: Final = "observation_station_code"
CONF_OBSERVATION_STATION_NAME: Final = "observation_station_name"
CONF_WARNING_AREA_CODE: Final = "warning_area_code"
CONF_WARNING_AREA_NAME: Final = "warning_area_name"
CONF_WARNING_OFFICE_CODE: Final = "warning_office_code"
CONF_UPDATE_INTERVAL_MINUTES: Final = "update_interval_minutes"
CONF_ENABLED_WARNING_LEVELS: Final = "enabled_warning_levels"
CONF_ENABLED_ENTITY_GROUPS: Final = "enabled_entity_groups"
CONF_NAME: Final = "name"
CONF_LATITUDE: Final = "latitude"
CONF_LONGITUDE: Final = "longitude"

LEVEL_ADVISORY: Final = "advisory"
LEVEL_WARNING: Final = "warning"
LEVEL_DANGER_WARNING: Final = "danger_warning"
LEVEL_EMERGENCY_WARNING: Final = "emergency_warning"

WARNING_LEVELS: Final[tuple[str, str, str, str]] = (
    LEVEL_ADVISORY,
    LEVEL_WARNING,
    LEVEL_DANGER_WARNING,
    LEVEL_EMERGENCY_WARNING,
)
DEFAULT_ENABLED_WARNING_LEVELS: Final[tuple[str, str, str, str]] = WARNING_LEVELS
WARNING_LEVEL_LABELS: Final[dict[str, str]] = {
    LEVEL_ADVISORY: "注意報",
    LEVEL_WARNING: "警報",
    LEVEL_DANGER_WARNING: "危険警報",
    LEVEL_EMERGENCY_WARNING: "特別警報",
}

ENTITY_GROUP_WEATHER_FORECAST: Final = "weather_forecast"
ENTITY_GROUP_WARNINGS: Final = "warnings"
ENTITY_GROUP_MANAGEMENT: Final = "management"
ENTITY_GROUPS: Final[tuple[str, str, str]] = (
    ENTITY_GROUP_WEATHER_FORECAST,
    ENTITY_GROUP_WARNINGS,
    ENTITY_GROUP_MANAGEMENT,
)
DEFAULT_ENABLED_ENTITY_GROUPS: Final[tuple[str, str, str]] = ENTITY_GROUPS
LEGACY_DEFAULT_ENABLED_ENTITY_GROUPS: Final[tuple[str, str, str]] = (
    ENTITY_GROUP_WEATHER_FORECAST,
    ENTITY_GROUP_WARNINGS,
    ENTITY_GROUP_MANAGEMENT,
)
RECOMMENDED_ENABLED_ENTITY_GROUPS: Final[tuple[str, str, str]] = (
    ENTITY_GROUP_WEATHER_FORECAST,
    ENTITY_GROUP_WARNINGS,
    ENTITY_GROUP_MANAGEMENT,
)
ENTITY_GROUP_LABELS: Final[dict[str, str]] = {
    ENTITY_GROUP_WEATHER_FORECAST: "天気予報",
    ENTITY_GROUP_WARNINGS: "注意報・警報",
    ENTITY_GROUP_MANAGEMENT: "管理ツール",
}
LEGACY_ENTITY_GROUP_MAP: Final[dict[str, str]] = {
    "forecast_sensors": ENTITY_GROUP_WEATHER_FORECAST,
    "warning_summary": ENTITY_GROUP_WARNINGS,
    "warning_binary_sensors": ENTITY_GROUP_WARNINGS,
    "location_info": ENTITY_GROUP_MANAGEMENT,
    "actions": ENTITY_GROUP_MANAGEMENT,
}

WEATHER_ENTITY_KEY: Final = "weather"
SENSOR_FORECAST_AREA: Final = "forecast_area"
SENSOR_OBSERVATION_STATION: Final = "observation_station"
SENSOR_REPORT_DATETIME: Final = "report_datetime"
SENSOR_PUBLISHING_OFFICE: Final = "publishing_office"
SENSOR_TODAY_PRECIP: Final = "today_precip_probability"
SENSOR_TOMORROW_PRECIP: Final = "tomorrow_precip_probability"
SENSOR_ALERT_SUMMARY: Final = "alert_summary"
SENSOR_ALERT_MAX_LEVEL: Final = "alert_max_level"
SENSOR_LAST_API_CALL_AT: Final = "last_api_call_at"
BUTTON_FORCE_REFRESH: Final = "force_refresh"

UNKNOWN_WEATHER_CONDITION: Final = "unknown"

# Limit entity definitions to the combinations that currently exist in JMA's
# published warning/advisory taxonomy.
WARNING_ENTITY_TITLES: Final[dict[tuple[str, str], str]] = {
    ("blizzard", LEVEL_ADVISORY): "レベル２風雪注意報",
    ("blizzard", LEVEL_WARNING): "レベル３暴風雪警報",
    ("blizzard", LEVEL_EMERGENCY_WARNING): "レベル５暴風雪特別警報",
    ("heavy_rain", LEVEL_ADVISORY): "レベル２大雨注意報",
    ("heavy_rain", LEVEL_WARNING): "レベル３大雨警報",
    ("heavy_rain", LEVEL_DANGER_WARNING): "レベル４大雨危険警報",
    ("heavy_rain", LEVEL_EMERGENCY_WARNING): "レベル５大雨特別警報",
    ("flood", LEVEL_ADVISORY): "レベル２洪水注意報",
    ("flood", LEVEL_WARNING): "レベル３洪水警報",
    ("landslide", LEVEL_ADVISORY): "レベル２土砂災害注意報",
    ("landslide", LEVEL_WARNING): "レベル３土砂災害警報",
    ("landslide", LEVEL_DANGER_WARNING): "レベル４土砂災害危険警報",
    ("landslide", LEVEL_EMERGENCY_WARNING): "レベル５土砂災害特別警報",
    ("storm", LEVEL_ADVISORY): "レベル２強風注意報",
    ("storm", LEVEL_WARNING): "レベル３暴風警報",
    ("storm", LEVEL_EMERGENCY_WARNING): "レベル５暴風特別警報",
    ("heavy_snow", LEVEL_ADVISORY): "レベル２大雪注意報",
    ("heavy_snow", LEVEL_WARNING): "レベル３大雪警報",
    ("heavy_snow", LEVEL_EMERGENCY_WARNING): "レベル５大雪特別警報",
    ("high_wave", LEVEL_ADVISORY): "レベル２波浪注意報",
    ("high_wave", LEVEL_WARNING): "レベル３波浪警報",
    ("high_wave", LEVEL_EMERGENCY_WARNING): "レベル５波浪特別警報",
    ("storm_surge", LEVEL_ADVISORY): "レベル２高潮注意報",
    ("storm_surge", LEVEL_WARNING): "レベル３高潮警報",
    ("storm_surge", LEVEL_DANGER_WARNING): "レベル４高潮危険警報",
    ("storm_surge", LEVEL_EMERGENCY_WARNING): "レベル５高潮特別警報",
    ("thunder", LEVEL_ADVISORY): "レベル２雷注意報",
    ("thaw", LEVEL_ADVISORY): "レベル２融雪注意報",
    ("fog", LEVEL_ADVISORY): "レベル２濃霧注意報",
    ("dry", LEVEL_ADVISORY): "レベル２乾燥注意報",
    ("avalanche", LEVEL_ADVISORY): "レベル２なだれ注意報",
    ("low_temp", LEVEL_ADVISORY): "レベル２低温注意報",
    ("frost", LEVEL_ADVISORY): "レベル２霜注意報",
    ("icing", LEVEL_ADVISORY): "レベル２着氷注意報",
    ("snow_accretion", LEVEL_ADVISORY): "レベル２着雪注意報",
}

_WARNING_CODE_TYPES: Final[dict[str, tuple[str, str]]] = {
    "02": ("blizzard", LEVEL_WARNING),
    "03": ("heavy_rain", LEVEL_WARNING),
    "04": ("flood", LEVEL_WARNING),
    "05": ("storm", LEVEL_WARNING),
    "06": ("heavy_snow", LEVEL_WARNING),
    "07": ("high_wave", LEVEL_WARNING),
    "08": ("storm_surge", LEVEL_WARNING),
    "09": ("landslide", LEVEL_WARNING),
    "10": ("heavy_rain", LEVEL_ADVISORY),
    "12": ("heavy_snow", LEVEL_ADVISORY),
    "13": ("blizzard", LEVEL_ADVISORY),
    "14": ("thunder", LEVEL_ADVISORY),
    "15": ("storm", LEVEL_ADVISORY),
    "16": ("high_wave", LEVEL_ADVISORY),
    "17": ("thaw", LEVEL_ADVISORY),
    "18": ("flood", LEVEL_ADVISORY),
    "19": ("storm_surge", LEVEL_ADVISORY),
    "20": ("fog", LEVEL_ADVISORY),
    "21": ("dry", LEVEL_ADVISORY),
    "22": ("avalanche", LEVEL_ADVISORY),
    "23": ("low_temp", LEVEL_ADVISORY),
    "24": ("frost", LEVEL_ADVISORY),
    "25": ("icing", LEVEL_ADVISORY),
    "26": ("snow_accretion", LEVEL_ADVISORY),
    "29": ("landslide", LEVEL_ADVISORY),
    "32": ("blizzard", LEVEL_EMERGENCY_WARNING),
    "33": ("heavy_rain", LEVEL_EMERGENCY_WARNING),
    "35": ("storm", LEVEL_EMERGENCY_WARNING),
    "36": ("heavy_snow", LEVEL_EMERGENCY_WARNING),
    "37": ("high_wave", LEVEL_EMERGENCY_WARNING),
    "38": ("storm_surge", LEVEL_EMERGENCY_WARNING),
    "39": ("landslide", LEVEL_EMERGENCY_WARNING),
    "43": ("heavy_rain", LEVEL_DANGER_WARNING),
    "48": ("storm_surge", LEVEL_DANGER_WARNING),
    "49": ("landslide", LEVEL_DANGER_WARNING),
}

WARNING_CODE_MAP: Final[dict[str, tuple[str, str, str]]] = {
    code: (warning_type, level, WARNING_ENTITY_TITLES[(warning_type, level)])
    for code, (warning_type, level) in _WARNING_CODE_TYPES.items()
}

ACTIVE_WARNING_STATUSES: Final[frozenset[str]] = frozenset(
    {"発表", "継続", "特別警報発表", "警報発表", "注意報発表"}
)
INACTIVE_WARNING_STATUSES: Final[frozenset[str]] = frozenset(
    {"解除", "発表警報・注意報はなし", "対象外"}
)
