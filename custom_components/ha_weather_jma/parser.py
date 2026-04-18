"""Pure parsing and normalization helpers for ha-weather-jma."""

from __future__ import annotations

import logging
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from itertools import zip_longest
from typing import Any, TypedDict
from xml.etree import ElementTree as ET

from .const import (
    ACTIVE_WARNING_STATUSES,
    CONF_ENABLED_ENTITY_GROUPS,
    CONF_ENABLED_WARNING_LEVELS,
    CONF_FORECAST_AREA_CODE,
    CONF_FORECAST_AREA_NAME,
    CONF_FORECAST_OFFICE_CODE,
    CONF_FORECAST_OFFICE_NAME,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_OBSERVATION_STATION_CODE,
    CONF_OBSERVATION_STATION_NAME,
    CONF_UPDATE_INTERVAL_MINUTES,
    CONF_WARNING_AREA_CODE,
    CONF_WARNING_AREA_NAME,
    CONF_WARNING_OFFICE_CODE,
    DEFAULT_ENABLED_ENTITY_GROUPS,
    DEFAULT_ENABLED_WARNING_LEVELS,
    DEFAULT_UPDATE_INTERVAL_MINUTES,
    ENTITY_GROUPS,
    INACTIVE_WARNING_STATUSES,
    LEVEL_ADVISORY,
    LEVEL_DANGER_WARNING,
    LEVEL_EMERGENCY_WARNING,
    LEVEL_WARNING,
    UNKNOWN_WEATHER_CONDITION,
    WARNING_CODE_MAP,
    WARNING_ENTITY_TITLES,
    WARNING_LEVELS,
)

_LOGGER = logging.getLogger(__name__)
_JST = timezone(timedelta(hours=9))
_LEVEL_PRIORITY = {
    LEVEL_ADVISORY: 1,
    LEVEL_WARNING: 2,
    LEVEL_DANGER_WARNING: 3,
    LEVEL_EMERGENCY_WARNING: 4,
}
_WIND_DIRECTION_DEGREES = {
    0: None,
    1: 22,
    2: 45,
    3: 68,
    4: 90,
    5: 112,
    6: 135,
    7: 158,
    8: 180,
    9: 202,
    10: 225,
    11: 248,
    12: 270,
    13: 292,
    14: 315,
    15: 338,
    16: 0,
}


class HaWeatherJmaParserError(ValueError):
    """Base parser error."""


class ForecastAreaNotFoundError(HaWeatherJmaParserError):
    """Raised when a forecast area is not present in the payload."""


class ObservationUnavailableError(HaWeatherJmaParserError):
    """Raised when a station payload is unusable."""


class WarningAreaNotFoundError(HaWeatherJmaParserError):
    """Raised when a warning area is not present in the payload."""


@dataclass(slots=True, frozen=True)
class ForecastAreaCandidate:
    """Forecast area candidate."""

    code: str
    name: str
    office_code: str
    office_name: str

    @property
    def display_label(self) -> str:
        return f"{self.office_name} / {self.name} ({self.code})"


@dataclass(slots=True, frozen=True)
class RegionCandidate:
    """Broad region candidate derived from area.json centers."""

    code: str
    name: str

    @property
    def display_label(self) -> str:
        return f"{self.name} ({self.code})"


@dataclass(slots=True, frozen=True)
class WarningAreaCandidate:
    """Warning area candidate."""

    code: str
    name: str
    office_code: str
    office_name: str

    @property
    def display_label(self) -> str:
        return f"{self.office_name} / {self.name} ({self.code})"


@dataclass(slots=True, frozen=True)
class ObservationStationCandidate:
    """Observation station candidate."""

    code: str
    name: str
    latitude: float | None
    longitude: float | None

    @property
    def display_label(self) -> str:
        return f"{self.name} ({self.code})"


@dataclass(slots=True, frozen=True)
class LocationConfig:
    """Normalized config entry data."""

    entry_id: str
    entry_slug: str
    name: str
    forecast_area_code: str
    forecast_area_name: str
    forecast_office_code: str
    forecast_office_name: str
    observation_station_code: str
    observation_station_name: str
    warning_area_code: str
    warning_area_name: str
    warning_office_code: str
    latitude: float | None
    longitude: float | None
    update_interval_minutes: int
    enabled_warning_levels: tuple[str, ...]
    enabled_entity_groups: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class ObservationSnapshot:
    """Normalized AMeDAS observation."""

    observed_at: datetime | None
    temperature_c: float | None
    humidity_percent: int | None
    wind_speed_ms: float | None
    wind_direction_deg: int | None
    pressure_hpa: float | None
    condition_code: str | None
    condition_text: str | None


@dataclass(slots=True, frozen=True)
class ForecastDaily:
    """One daily forecast."""

    target_date: date
    condition_code: str | None
    condition_text: str | None
    precip_probability_percent: int | None
    temp_min_c: float | None
    temp_max_c: float | None
    wind_text: str | None
    sunrise_at: datetime | None = None
    sunset_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class AlertItem:
    """One warning type/level state."""

    warning_code: str | None
    warning_type: str
    level: str
    title: str
    is_active: bool | None
    status_text: str | None
    area_code: str
    area_name: str
    report_datetime: datetime | None
    publishing_office: str | None
    headline_text: str | None


@dataclass(slots=True, frozen=True)
class AlertSummary:
    """Aggregate warning state."""

    max_level: str | None
    active_types: tuple[str, ...]
    active_titles: tuple[str, ...]
    headline_text: str | None
    report_datetime: datetime | None
    publishing_office: str | None


@dataclass(slots=True, frozen=True)
class ForecastMetadata:
    """Forecast metadata."""

    report_datetime: datetime | None
    publishing_office: str | None


class WarningXmlMetadata(TypedDict):
    """Metadata extracted from the newest warning XML document."""

    report_datetime: datetime | None
    publishing_office: str | None
    headline_text: str | None


@dataclass(slots=True, frozen=True)
class CoordinatorSnapshot:
    """Coordinator payload."""

    location: LocationConfig
    observation: ObservationSnapshot | None
    forecast_days: tuple[ForecastDaily, ...]
    forecast_meta: ForecastMetadata
    alerts: dict[tuple[str, str], AlertItem]
    alert_summary: AlertSummary
    last_success_at: datetime | None
    is_partial: bool


def build_forecast_area_candidates(
    raw: Mapping[str, Any],
) -> dict[str, ForecastAreaCandidate]:
    """Build forecast area choices from area.json."""
    offices = _mapping(raw.get("offices"))
    class10s = _mapping(raw.get("class10s"))
    candidates: dict[str, ForecastAreaCandidate] = {}

    for office_code in sorted(offices):
        office = _mapping(offices[office_code])
        office_name = str(office.get("officeName") or office.get("name") or office_code)
        for child_code in _iter_strings(office.get("children")):
            area = _mapping(class10s.get(child_code))
            if not area:
                continue
            candidates[child_code] = ForecastAreaCandidate(
                code=child_code,
                name=str(area.get("name") or child_code),
                office_code=office_code,
                office_name=office_name,
            )

    return candidates


def build_region_candidates(raw: Mapping[str, Any]) -> dict[str, RegionCandidate]:
    """Build broad region choices from area.json centers referenced by offices."""
    centers = _mapping(raw.get("centers"))
    offices = _mapping(raw.get("offices"))
    candidates: dict[str, RegionCandidate] = {}

    for office_code in sorted(offices):
        office = _mapping(offices[office_code])
        center_code = str(office.get("parent") or "")
        if not center_code or center_code in candidates:
            continue

        center = _mapping(centers.get(center_code))
        center_name = str(center.get("name") or center_code)
        candidates[center_code] = RegionCandidate(
            code=center_code,
            name=center_name,
        )

    return candidates


def build_warning_area_candidates(
    raw: Mapping[str, Any],
) -> dict[str, WarningAreaCandidate]:
    """Build warning area choices from area.json."""
    candidates: dict[str, WarningAreaCandidate] = {}
    class20s = _mapping(raw.get("class20s"))

    for code in sorted(class20s):
        area = _mapping(class20s[code])
        office_code, office_name = resolve_warning_office(raw, code)
        candidates[code] = WarningAreaCandidate(
            code=code,
            name=str(area.get("name") or code),
            office_code=office_code,
            office_name=office_name,
        )

    return candidates


def build_observation_station_candidates(
    raw: Mapping[str, Any],
) -> dict[str, ObservationStationCandidate]:
    """Build observation station choices from amedastable.json."""
    candidates: dict[str, ObservationStationCandidate] = {}

    for code in sorted(raw):
        station = _mapping(raw[code])
        candidates[code] = ObservationStationCandidate(
            code=code,
            name=str(station.get("kjName") or station.get("enName") or code),
            latitude=_coerce_lat_lon(station.get("lat")),
            longitude=_coerce_lat_lon(station.get("lon")),
        )

    return candidates


def resolve_warning_office(
    raw: Mapping[str, Any], warning_area_code: str
) -> tuple[str, str]:
    """Resolve a class20 warning area to its office code and office name."""
    class20s = _mapping(raw.get("class20s"))
    class15s = _mapping(raw.get("class15s"))
    class10s = _mapping(raw.get("class10s"))
    offices = _mapping(raw.get("offices"))

    current = warning_area_code
    seen: set[str] = set()
    while current and current not in seen:
        seen.add(current)
        if current in offices:
            office = _mapping(offices[current])
            return current, str(
                office.get("officeName") or office.get("name") or current
            )
        if current in class10s:
            office_code = str(_mapping(class10s[current]).get("parent") or "")
            office = _mapping(offices.get(office_code))
            if office:
                return office_code, str(
                    office.get("officeName") or office.get("name") or office_code
                )
            current = office_code
            continue
        if current in class15s:
            current = str(_mapping(class15s[current]).get("parent") or "")
            continue
        if current in class20s:
            current = str(_mapping(class20s[current]).get("parent") or "")
            continue
        break

    raise WarningAreaNotFoundError(
        f"Unable to resolve office for warning area {warning_area_code}"
    )


def build_location_config(
    entry_id: str, title: str, data: Mapping[str, Any]
) -> LocationConfig:
    """Normalize config entry data."""
    enabled_levels = (
        tuple(
            level
            for level in _iter_strings(data.get(CONF_ENABLED_WARNING_LEVELS))
            if level in WARNING_LEVELS
        )
        or DEFAULT_ENABLED_WARNING_LEVELS
    )
    raw_entity_groups = data.get(CONF_ENABLED_ENTITY_GROUPS)
    enabled_entity_groups = (
        tuple(
            group
            for group in _iter_strings(raw_entity_groups)
            if group in ENTITY_GROUPS
        )
        if raw_entity_groups is not None
        else DEFAULT_ENABLED_ENTITY_GROUPS
    )

    entry_slug = (
        slugify_name(title)
        or slugify_name(entry_id)
        or "ha_weather_jma_entry"
    )
    return LocationConfig(
        entry_id=entry_id,
        entry_slug=entry_slug,
        name=title,
        forecast_area_code=str(data[CONF_FORECAST_AREA_CODE]),
        forecast_area_name=str(data[CONF_FORECAST_AREA_NAME]),
        forecast_office_code=str(data[CONF_FORECAST_OFFICE_CODE]),
        forecast_office_name=str(data[CONF_FORECAST_OFFICE_NAME]),
        observation_station_code=str(data[CONF_OBSERVATION_STATION_CODE]),
        observation_station_name=str(data[CONF_OBSERVATION_STATION_NAME]),
        warning_area_code=str(data[CONF_WARNING_AREA_CODE]),
        warning_area_name=str(data[CONF_WARNING_AREA_NAME]),
        warning_office_code=str(data[CONF_WARNING_OFFICE_CODE]),
        latitude=_coerce_float(data.get(CONF_LATITUDE)),
        longitude=_coerce_float(data.get(CONF_LONGITUDE)),
        update_interval_minutes=_coerce_int(data.get(CONF_UPDATE_INTERVAL_MINUTES))
        or DEFAULT_UPDATE_INTERVAL_MINUTES,
        enabled_warning_levels=enabled_levels,
        enabled_entity_groups=enabled_entity_groups,
    )


def parse_observation(raw: Mapping[str, Any], latest_time: str) -> ObservationSnapshot:
    """Normalize a single AMeDAS station payload."""
    if not raw:
        raise ObservationUnavailableError("Empty observation payload")

    return ObservationSnapshot(
        observed_at=parse_datetime(latest_time),
        temperature_c=_coerce_float(_extract_primary_value(raw.get("temp"))),
        humidity_percent=_coerce_int(_extract_primary_value(raw.get("humidity"))),
        wind_speed_ms=_coerce_float(_extract_primary_value(raw.get("wind"))),
        wind_direction_deg=_wind_code_to_degrees(
            _coerce_int(_extract_primary_value(raw.get("windDirection")))
        ),
        pressure_hpa=_coerce_float(_extract_primary_value(raw.get("pressure"))),
        condition_code=text_or_none(
            _extract_primary_value(
                _first_present(raw, "weatherCode", "conditionCode", "condition_code")
            )
        ),
        condition_text=text_or_none(
            _extract_primary_value(
                _first_present(
                    raw,
                    "weather",
                    "condition",
                    "conditionText",
                    "condition_text",
                )
            )
        ),
    )


def parse_forecast(
    raw: Sequence[Mapping[str, Any]],
    forecast_area_code: str,
    observation_station_code: str | None = None,
) -> tuple[ForecastDaily, ...]:
    """Normalize forecast JSON into daily forecasts."""
    if not raw:
        raise ForecastAreaNotFoundError("Forecast payload is empty")

    short_block = _mapping(raw[0]) if raw else {}
    weekly_block = _mapping(raw[1]) if len(raw) > 1 else {}
    by_date: dict[date, dict[str, Any]] = defaultdict(dict)

    short_weather_series = _find_time_series(short_block, {"weatherCodes", "weathers"})
    if short_weather_series is None:
        raise ForecastAreaNotFoundError("Short-term weather series missing")
    short_weather_area = _find_area(short_weather_series, forecast_area_code)
    if short_weather_area is None:
        raise ForecastAreaNotFoundError(f"Forecast area {forecast_area_code} not found")

    for defined_at, code, text, wind in zip_longest(
        _iter_strings(short_weather_series.get("timeDefines")),
        _iter_strings(short_weather_area.get("weatherCodes")),
        _iter_strings(short_weather_area.get("weathers")),
        _iter_strings(short_weather_area.get("winds")),
        fillvalue=None,
    ):
        dt_value = parse_datetime(defined_at)
        if dt_value is None:
            continue
        bucket = by_date[dt_value.date()]
        bucket.setdefault("condition_code", text_or_none(code))
        bucket.setdefault("condition_text", text_or_none(text))
        bucket.setdefault("wind_text", text_or_none(wind))

    short_pop_series = _find_time_series(short_block, {"pops"})
    short_pop_area = _find_area(short_pop_series, forecast_area_code)
    if short_pop_series is not None and short_pop_area is not None:
        aggregated_pops: dict[date, int] = {}
        for defined_at, pop in zip(
            _iter_strings(short_pop_series.get("timeDefines")),
            _iter_strings(short_pop_area.get("pops")),
            strict=False,
        ):
            dt_value = parse_datetime(defined_at)
            probability = _coerce_int(pop)
            if dt_value is None or probability is None:
                continue
            day = dt_value.date()
            existing = aggregated_pops.get(day)
            aggregated_pops[day] = (
                probability if existing is None else max(existing, probability)
            )
        for day, probability in aggregated_pops.items():
            by_date[day]["precip_probability_percent"] = probability

    short_temp_series = _find_time_series(short_block, {"temps"})
    short_temp_area = _find_area(short_temp_series, observation_station_code)
    if short_temp_series is not None and short_temp_area is not None:
        dates = [
            parse_datetime(value)
            for value in _iter_strings(short_temp_series.get("timeDefines"))
        ]
        temps = [
            _coerce_float(value)
            for value in _iter_strings(short_temp_area.get("temps"))
        ]
        if dates and dates[0] is not None:
            bucket = by_date[dates[0].date()]
            if temps:
                bucket["temp_min_c"] = temps[0]
            if len(temps) > 1:
                bucket["temp_max_c"] = temps[1]

    weekly_weather_series = _find_time_series(weekly_block, {"weatherCodes", "pops"})
    weekly_weather_area = _find_area(weekly_weather_series, forecast_area_code)
    if weekly_weather_series is not None and weekly_weather_area is not None:
        for defined_at, code, pop in zip(
            _iter_strings(weekly_weather_series.get("timeDefines")),
            _iter_strings(weekly_weather_area.get("weatherCodes")),
            _iter_strings(weekly_weather_area.get("pops")),
            strict=False,
        ):
            dt_value = parse_datetime(defined_at)
            if dt_value is None:
                continue
            bucket = by_date[dt_value.date()]
            bucket.setdefault("condition_code", text_or_none(code))
            bucket.setdefault("precip_probability_percent", _coerce_int(pop))

    weekly_temp_series = _find_time_series(weekly_block, {"tempsMin", "tempsMax"})
    weekly_temp_area = _find_area(weekly_temp_series, observation_station_code)
    if weekly_temp_series is not None and weekly_temp_area is not None:
        for defined_at, temp_min, temp_max in zip(
            _iter_strings(weekly_temp_series.get("timeDefines")),
            _iter_strings(weekly_temp_area.get("tempsMin")),
            _iter_strings(weekly_temp_area.get("tempsMax")),
            strict=False,
        ):
            dt_value = parse_datetime(defined_at)
            if dt_value is None:
                continue
            bucket = by_date[dt_value.date()]
            bucket.setdefault("temp_min_c", _coerce_float(temp_min))
            bucket.setdefault("temp_max_c", _coerce_float(temp_max))

    forecasts = tuple(
        ForecastDaily(
            target_date=target_date,
            condition_code=values.get("condition_code"),
            condition_text=values.get("condition_text"),
            precip_probability_percent=values.get("precip_probability_percent"),
            temp_min_c=values.get("temp_min_c"),
            temp_max_c=values.get("temp_max_c"),
            wind_text=values.get("wind_text"),
        )
        for target_date, values in sorted(by_date.items())
        if values
    )
    if not forecasts:
        raise ForecastAreaNotFoundError(
            f"Forecast data for area {forecast_area_code} is empty"
        )
    return forecasts


def forecast_supports_observation_station(
    raw: Sequence[Mapping[str, Any]],
    observation_station_code: str | None,
) -> bool:
    """Return whether the forecast payload contains temperatures for the station."""
    if observation_station_code is None:
        return False

    return observation_station_code in extract_forecast_observation_station_codes(raw)


def extract_forecast_observation_station_codes(
    raw: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Extract station codes that have temperature series in the forecast payload."""
    station_codes: set[str] = set()

    for block in raw:
        for series in _iter_mappings(_mapping(block).get("timeSeries")):
            areas = list(_iter_mappings(series.get("areas")))
            if not areas:
                continue
            area_keys = set(areas[0].keys())
            if not (
                "temps" in area_keys
                or "tempsMin" in area_keys
                or "tempsMax" in area_keys
            ):
                continue
            for area in areas:
                area_code = text_or_none(_mapping(area.get("area")).get("code"))
                if area_code is not None:
                    station_codes.add(area_code)

    return tuple(sorted(station_codes))


def parse_forecast_metadata(raw: Sequence[Mapping[str, Any]]) -> ForecastMetadata:
    """Extract forecast-level metadata."""
    block = _mapping(raw[0]) if raw else {}
    return ForecastMetadata(
        report_datetime=parse_datetime(block.get("reportDatetime")),
        publishing_office=text_or_none(block.get("publishingOffice")),
    )


def parse_alerts_xml(
    raw_documents: Iterable[str],
    warning_area_code: str,
    warning_area_name: str,
) -> dict[tuple[str, str], AlertItem]:
    """Normalize warning XML documents into fixed alert items.

    Warning parsing is XML-first so the integration can follow the 2026
    warning-system products and status transitions directly from JMAXML.
    """
    documents = [text for text in raw_documents if text and text.strip()]
    if not documents:
        raise WarningAreaNotFoundError("Warning XML payload is empty")

    latest_meta = _latest_warning_xml_metadata(documents)
    alerts = build_default_alerts(
        warning_area_code=warning_area_code,
        warning_area_name=warning_area_name,
        report_datetime=latest_meta["report_datetime"],
        publishing_office=latest_meta["publishing_office"],
        headline_text=latest_meta["headline_text"],
        unavailable=False,
    )

    matched = False
    for document in documents:
        try:
            root = ET.fromstring(document)
        except ET.ParseError as err:
            raise HaWeatherJmaParserError("Invalid warning XML payload") from err

        report_datetime = parse_datetime(
            _xml_find_text(root, ".//{*}Head/{*}ReportDateTime")
        )
        publishing_office = text_or_none(
            _xml_find_text(root, "./{*}Control/{*}PublishingOffice")
        )
        headline_text = text_or_none(_xml_find_text(root, ".//{*}Headline/{*}Text"))

        for item in root.findall(
            ".//{*}Body/{*}Warning[@type='気象警報・注意報（市町村等）']/{*}Item"
        ):
            area_code = text_or_none(_xml_find_text(item, "./{*}Area/{*}Code"))
            if area_code != warning_area_code:
                continue
            matched = True
            for kind in item.findall("./{*}Kind"):
                code = text_or_none(_xml_find_text(kind, "./{*}Code"))
                if code is None:
                    continue
                code_key = str(code).zfill(2)
                mapping = WARNING_CODE_MAP.get(code_key)
                if mapping is None:
                    _LOGGER.warning("Ignoring unknown JMA warning code: %s", code_key)
                    continue
                warning_type, level, title = mapping
                new_item = AlertItem(
                    warning_code=code_key,
                    warning_type=warning_type,
                    level=level,
                    title=title,
                    is_active=_warning_status_to_state(
                        text_or_none(_xml_find_text(kind, "./{*}Status"))
                    ),
                    status_text=text_or_none(_xml_find_text(kind, "./{*}Status")),
                    area_code=warning_area_code,
                    area_name=warning_area_name,
                    report_datetime=report_datetime,
                    publishing_office=publishing_office,
                    headline_text=headline_text,
                )
                key = (warning_type, level)
                if _should_replace_alert(alerts[key], new_item):
                    alerts[key] = new_item

    if not matched:
        raise WarningAreaNotFoundError(f"Warning area {warning_area_code} not found")
    return alerts


def build_default_alerts(
    *,
    warning_area_code: str,
    warning_area_name: str,
    report_datetime: datetime | None,
    publishing_office: str | None,
    headline_text: str | None,
    unavailable: bool,
) -> dict[tuple[str, str], AlertItem]:
    """Build the fixed alert key space."""
    state = None if unavailable else False
    status_text = None if unavailable else "対象外"
    return {
        (warning_type, level): AlertItem(
            warning_code=None,
            warning_type=warning_type,
            level=level,
            title=warning_entity_title(warning_type, level),
            is_active=state,
            status_text=status_text,
            area_code=warning_area_code,
            area_name=warning_area_name,
            report_datetime=report_datetime,
            publishing_office=publishing_office,
            headline_text=headline_text,
        )
        for warning_type, level in WARNING_ENTITY_TITLES
    }


def build_alert_summary(alerts: Mapping[tuple[str, str], AlertItem]) -> AlertSummary:
    """Aggregate alert items."""
    items = list(alerts.values())
    if items and all(item.is_active is None for item in items):
        reference = items[0]
        return AlertSummary(
            max_level=None,
            active_types=(),
            active_titles=(),
            headline_text=reference.headline_text,
            report_datetime=reference.report_datetime,
            publishing_office=reference.publishing_office,
        )

    active_items = sorted(
        (item for item in items if item.is_active),
        key=lambda item: (_LEVEL_PRIORITY[item.level], item.title),
        reverse=True,
    )
    if not active_items:
        fallback_reference = items[0] if items else None
        return AlertSummary(
            max_level="none",
            active_types=(),
            active_titles=(),
            headline_text=(
                fallback_reference.headline_text if fallback_reference else None
            ),
            report_datetime=(
                fallback_reference.report_datetime if fallback_reference else None
            ),
            publishing_office=(
                fallback_reference.publishing_office if fallback_reference else None
            ),
        )

    return AlertSummary(
        max_level=active_items[0].level,
        active_types=tuple(dict.fromkeys(item.warning_type for item in active_items)),
        active_titles=tuple(dict.fromkeys(item.title for item in active_items)),
        headline_text=active_items[0].headline_text,
        report_datetime=active_items[0].report_datetime,
        publishing_office=active_items[0].publishing_office,
    )


def build_snapshot(
    *,
    location: LocationConfig,
    observation: ObservationSnapshot | None,
    forecast_days: Iterable[ForecastDaily],
    forecast_meta: ForecastMetadata,
    alerts: dict[tuple[str, str], AlertItem],
    alert_summary: AlertSummary,
    last_success_at: datetime | None,
    is_partial: bool,
) -> CoordinatorSnapshot:
    """Build the coordinator snapshot."""
    return CoordinatorSnapshot(
        location=location,
        observation=observation,
        forecast_days=tuple(forecast_days),
        forecast_meta=forecast_meta,
        alerts=alerts,
        alert_summary=alert_summary,
        last_success_at=last_success_at,
        is_partial=is_partial,
    )


def warning_entity_title(warning_type: str, level: str) -> str:
    """Return the display title for a warning entity."""
    return WARNING_ENTITY_TITLES[(warning_type, level)]


def map_condition_to_ha(condition_code: str | None, condition_text: str | None) -> str:
    """Map JMA values to Home Assistant weather conditions."""
    text = (condition_text or "").replace("　", " ")
    if "雷" in text and ("雨" in text or "雪" in text):
        return "lightning-rainy"
    if "雷" in text:
        return "lightning"
    if "霧" in text:
        return "fog"
    if "雪" in text and "雨" in text:
        return "snowy-rainy"
    if "雪" in text:
        return "snowy"
    if "雨" in text:
        return "rainy"
    if "晴" in text and ("曇" in text or "くもり" in text):
        return "partlycloudy"
    if "曇" in text or "くもり" in text:
        return "cloudy"
    if "晴" in text:
        return "sunny"
    if condition_code:
        prefix = condition_code[:1]
        if prefix == "1":
            return "sunny"
        if prefix == "2":
            return "cloudy"
        if prefix == "3":
            return "rainy"
        if prefix == "4":
            return "snowy"
    return UNKNOWN_WEATHER_CONDITION


def resolve_weather_condition(
    observation: ObservationSnapshot | None,
    forecast_days: Iterable[ForecastDaily],
) -> tuple[str, str | None]:
    """Resolve the weather condition using the documented priority."""
    if observation is not None:
        condition = map_condition_to_ha(
            observation.condition_code, observation.condition_text
        )
        if condition != UNKNOWN_WEATHER_CONDITION:
            return condition, observation.condition_text
        if observation.condition_text:
            return UNKNOWN_WEATHER_CONDITION, observation.condition_text

    today = next(iter(forecast_days), None)
    if today is not None:
        return (
            map_condition_to_ha(today.condition_code, today.condition_text),
            today.condition_text,
        )

    return UNKNOWN_WEATHER_CONDITION, None


def first_two_forecast_days(
    forecast_days: Iterable[ForecastDaily],
) -> tuple[ForecastDaily | None, ForecastDaily | None]:
    """Return the first two forecast days."""
    items = list(forecast_days)
    return (items[0] if items else None, items[1] if len(items) > 1 else None)


def forecast_datetime_utc(target_date: date) -> str:
    """Return a UTC RFC3339 string for daily forecast timestamps."""
    return (
        datetime.combine(target_date, time.min, tzinfo=_JST)
        .astimezone(timezone.utc)
        .isoformat()
    )


def slugify_name(value: str) -> str:
    """Convert a string to a simple slug."""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "_", ascii_value).strip("_")


def parse_datetime(value: Any) -> datetime | None:
    """Parse an ISO 8601 datetime string."""
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def text_or_none(value: Any) -> str | None:
    """Convert a value to a trimmed string or None."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _should_replace_alert(existing: AlertItem, new_item: AlertItem) -> bool:
    return _alert_state_rank(new_item.is_active) >= _alert_state_rank(
        existing.is_active
    )


def _alert_state_rank(value: bool | None) -> int:
    if value is True:
        return 3
    if value is None:
        return 2
    return 1


def _warning_status_to_state(status_text: str | None) -> bool | None:
    if status_text in ACTIVE_WARNING_STATUSES:
        return True
    if status_text in INACTIVE_WARNING_STATUSES:
        return False
    if status_text and "から" in status_text and "解除" not in status_text:
        return True
    if status_text and "発表" in status_text and "なし" not in status_text:
        return True
    if status_text and "継続" in status_text:
        return True
    if status_text:
        _LOGGER.warning("Unknown JMA warning status: %s", status_text)
    return None


def _find_time_series(
    block: Mapping[str, Any],
    required_area_keys: set[str],
) -> Mapping[str, Any] | None:
    for series in _iter_mappings(block.get("timeSeries")):
        areas = list(_iter_mappings(series.get("areas")))
        if areas and required_area_keys.issubset(set(areas[0].keys())):
            return series
    return None


def _find_area(
    series: Mapping[str, Any] | None, target_code: str | None
) -> Mapping[str, Any] | None:
    if series is None or target_code is None:
        return None
    for area in _iter_mappings(series.get("areas")):
        if str(_mapping(area.get("area")).get("code")) == target_code:
            return area
    return None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first_present(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _iter_mappings(value: Any) -> Iterable[Mapping[str, Any]]:
    if not isinstance(value, list):
        return ()
    return (item for item in value if isinstance(item, Mapping))


def _iter_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _coerce_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_lat_lon(value: Any) -> float | None:
    if not isinstance(value, list) or len(value) < 2:
        return None
    degrees = _coerce_float(value[0])
    minutes = _coerce_float(value[1])
    if degrees is None or minutes is None:
        return None
    return degrees + (minutes / 60.0)


def _extract_primary_value(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _wind_code_to_degrees(code: int | None) -> int | None:
    if code is None:
        return None
    return _WIND_DIRECTION_DEGREES.get(code)


def _xml_find_text(element: ET.Element, path: str) -> str | None:
    target = element.find(path)
    if target is None or target.text is None:
        return None
    return target.text


def _latest_warning_xml_metadata(
    raw_documents: Iterable[str],
) -> WarningXmlMetadata:
    latest_key: datetime | None = None
    latest_meta: WarningXmlMetadata = {
        "report_datetime": None,
        "publishing_office": None,
        "headline_text": None,
    }
    for document in raw_documents:
        try:
            root = ET.fromstring(document)
        except ET.ParseError as err:
            raise HaWeatherJmaParserError("Invalid warning XML payload") from err
        report_datetime = parse_datetime(
            _xml_find_text(root, ".//{*}Head/{*}ReportDateTime")
        )
        if latest_key is None or (
            report_datetime is not None and report_datetime >= latest_key
        ):
            latest_key = report_datetime
            latest_meta = {
                "report_datetime": report_datetime,
                "publishing_office": text_or_none(
                    _xml_find_text(root, "./{*}Control/{*}PublishingOffice")
                ),
                "headline_text": text_or_none(
                    _xml_find_text(root, ".//{*}Headline/{*}Text")
                ),
            }
    return latest_meta
