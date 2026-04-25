"""Config flow for ha-weather-jma."""

# mypy: disable-error-code=call-arg

from __future__ import annotations

import asyncio
import math
import unicodedata
from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HaWeatherJmaApiClient
from .const import (
    CONF_ENABLED_ENTITY_GROUPS,
    CONF_ENABLED_WARNING_LEVELS,
    CONF_FORECAST_AREA_CODE,
    CONF_FORECAST_AREA_NAME,
    CONF_FORECAST_OFFICE_CODE,
    CONF_FORECAST_OFFICE_NAME,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_NAME,
    CONF_OBSERVATION_STATION_CODE,
    CONF_OBSERVATION_STATION_NAME,
    CONF_UPDATE_INTERVAL_MINUTES,
    CONF_WARNING_AREA_CODE,
    CONF_WARNING_AREA_NAME,
    CONF_WARNING_OFFICE_CODE,
    DEFAULT_ENABLED_ENTITY_GROUPS,
    DEFAULT_ENABLED_WARNING_LEVELS,
    DEFAULT_UPDATE_INTERVAL_MINUTES,
    DOMAIN,
    ENTITY_GROUP_LABELS,
    ENTITY_GROUP_WARNING_BINARY_SENSORS,
    MAX_UPDATE_INTERVAL_MINUTES,
    MIN_UPDATE_INTERVAL_MINUTES,
    RECOMMENDED_ENABLED_ENTITY_GROUPS,
    WARNING_LEVEL_LABELS,
)
from .parser import (
    ForecastAreaCandidate,
    HaWeatherJmaParserError,
    ObservationStationCandidate,
    RegionCandidate,
    WarningAreaCandidate,
    build_forecast_area_candidates,
    build_observation_station_candidates,
    build_region_candidates,
    build_warning_area_candidates,
    extract_forecast_observation_station_codes,
)

CandidateMap = Mapping[
    str,
    ForecastAreaCandidate
    | ObservationStationCandidate
    | RegionCandidate
    | WarningAreaCandidate,
]
ConfigFlowInput = dict[str, Any]
MAX_FILTERED_CANDIDATES = 100
MAX_NEARBY_OBSERVATION_CANDIDATES = 20
NEARBY_OBSERVATION_DISTANCE_KM = 30.0
CONF_FORECAST_AREA_QUERY = "forecast_area_query"
CONF_REGION_CODE = "region_code"
CONF_REGION_QUERY = "region_query"
CONF_OBSERVATION_STATION_QUERY = "observation_station_query"
CONF_WARNING_AREA_QUERY = "warning_area_query"
FILTER_FIELD_MAP = {
    CONF_REGION_CODE: CONF_REGION_QUERY,
    CONF_FORECAST_AREA_CODE: CONF_FORECAST_AREA_QUERY,
    CONF_OBSERVATION_STATION_CODE: CONF_OBSERVATION_STATION_QUERY,
    CONF_WARNING_AREA_CODE: CONF_WARNING_AREA_QUERY,
}
CONNECTIVITY_ERRORS = (
    aiohttp.ClientError,
    asyncio.TimeoutError,
    HaWeatherJmaParserError,
    LookupError,
    ValueError,
)


def build_options_schema(
    *,
    default_update_interval: int,
    default_warning_levels: list[str],
    default_entity_groups: list[str],
    default_name: str | None = None,
) -> vol.Schema:
    """Build the shared create/options form schema."""
    schema_fields: dict[Any, Any] = {
        vol.Required(
            CONF_UPDATE_INTERVAL_MINUTES,
            default=default_update_interval,
        ): vol.All(
            vol.Coerce(int),
            vol.Range(
                min=MIN_UPDATE_INTERVAL_MINUTES,
                max=MAX_UPDATE_INTERVAL_MINUTES,
            ),
        ),
        vol.Required(
            CONF_ENABLED_WARNING_LEVELS,
            default=default_warning_levels,
        ): cv.multi_select(WARNING_LEVEL_LABELS),
        vol.Required(
            CONF_ENABLED_ENTITY_GROUPS,
            default=default_entity_groups,
        ): cv.multi_select(ENTITY_GROUP_LABELS),
    }
    if default_name is not None:
        schema_fields = {
            vol.Required(CONF_NAME, default=default_name): str,
            **schema_fields,
        }
    return vol.Schema(schema_fields)


class HaWeatherJmaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for ha-weather-jma."""

    VERSION = 1

    def __init__(self) -> None:
        self._api_client: HaWeatherJmaApiClient | None = None
        self._region_candidates: dict[str, RegionCandidate] = {}
        self._office_region_codes: dict[str, str] = {}
        self._forecast_candidates: dict[str, ForecastAreaCandidate] = {}
        self._station_candidates: dict[str, ObservationStationCandidate] = {}
        self._observation_candidates: dict[str, ObservationStationCandidate] = {}
        self._warning_candidates: dict[str, WarningAreaCandidate] = {}
        self._candidate_filters: dict[str, str] = {}
        self._entry_data: ConfigFlowInput = {}

    async def async_step_user(self, user_input: ConfigFlowInput | None = None):
        """Select the broad region."""
        errors: dict[str, str] = {}
        try:
            candidates = await self._async_get_region_candidates()
        except CONNECTIVITY_ERRORS:
            return self._show_connect_error("user")

        self._update_candidate_filter(CONF_REGION_CODE, user_input)
        if user_input is not None:
            selected_code = user_input.get(CONF_REGION_CODE)
            if selected_code not in (None, ""):
                candidate = candidates.get(str(selected_code))
                if candidate is None:
                    errors["base"] = "invalid_selection"
                else:
                    self._candidate_filters.pop(CONF_FORECAST_AREA_CODE, None)
                    self._entry_data[CONF_REGION_CODE] = candidate.code
                    return await self.async_step_forecast_area()

        data_schema, filter_error = self._build_candidate_schema(
            CONF_REGION_CODE,
            candidates,
        )
        if not errors and filter_error is not None:
            errors["base"] = filter_error

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_forecast_area(
        self,
        user_input: ConfigFlowInput | None = None,
    ):
        """Select the forecast area."""
        errors: dict[str, str] = {}
        try:
            candidates = await self._async_get_forecast_candidates()
        except CONNECTIVITY_ERRORS:
            return self._show_connect_error("forecast_area")

        self._update_candidate_filter(CONF_FORECAST_AREA_CODE, user_input)
        if user_input is not None:
            selected_code = user_input.get(CONF_FORECAST_AREA_CODE)
            if selected_code not in (None, ""):
                candidate = candidates.get(str(selected_code))
                if candidate is None:
                    errors["base"] = "invalid_selection"
                else:
                    self._observation_candidates = {}
                    self._candidate_filters.pop(CONF_OBSERVATION_STATION_CODE, None)
                    self._entry_data.update(
                        {
                            CONF_FORECAST_AREA_CODE: candidate.code,
                            CONF_FORECAST_AREA_NAME: candidate.name,
                            CONF_FORECAST_OFFICE_CODE: candidate.office_code,
                            CONF_FORECAST_OFFICE_NAME: candidate.office_name,
                        }
                    )
                    return await self.async_step_observation()

        data_schema, filter_error = self._build_candidate_schema(
            CONF_FORECAST_AREA_CODE,
            candidates,
        )
        if not errors and filter_error is not None:
            errors["base"] = filter_error

        return self.async_show_form(
            step_id="forecast_area",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_observation(
        self,
        user_input: ConfigFlowInput | None = None,
    ):
        """Select the observation station."""
        errors: dict[str, str] = {}
        try:
            candidates = await self._async_get_observation_candidates()
        except CONNECTIVITY_ERRORS:
            return self._show_connect_error("observation")

        self._update_candidate_filter(CONF_OBSERVATION_STATION_CODE, user_input)
        if user_input is not None:
            selected_code = user_input.get(CONF_OBSERVATION_STATION_CODE)
            if selected_code not in (None, ""):
                candidate = candidates.get(str(selected_code))
                if candidate is None:
                    errors["base"] = "invalid_selection"
                else:
                    self._entry_data.update(
                        {
                            CONF_OBSERVATION_STATION_CODE: candidate.code,
                            CONF_OBSERVATION_STATION_NAME: candidate.name,
                            CONF_LATITUDE: candidate.latitude,
                            CONF_LONGITUDE: candidate.longitude,
                        }
                    )
                    return await self.async_step_warning()

        data_schema, filter_error = self._build_candidate_schema(
            CONF_OBSERVATION_STATION_CODE,
            candidates,
        )
        if not errors and filter_error is not None:
            errors["base"] = filter_error

        return self.async_show_form(
            step_id="observation",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_warning(self, user_input: ConfigFlowInput | None = None):
        """Select the warning area."""
        errors: dict[str, str] = {}
        try:
            candidates = await self._async_get_warning_candidates()
        except CONNECTIVITY_ERRORS:
            return self._show_connect_error("warning")

        self._update_candidate_filter(CONF_WARNING_AREA_CODE, user_input)
        if user_input is not None:
            selected_code = user_input.get(CONF_WARNING_AREA_CODE)
            if selected_code not in (None, ""):
                candidate = candidates.get(str(selected_code))
                if candidate is None:
                    errors["base"] = "invalid_selection"
                else:
                    self._entry_data.update(
                        {
                            CONF_WARNING_AREA_CODE: candidate.code,
                            CONF_WARNING_AREA_NAME: candidate.name,
                            CONF_WARNING_OFFICE_CODE: candidate.office_code,
                        }
                    )
                    return await self.async_step_options()

        data_schema, filter_error = self._build_candidate_schema(
            CONF_WARNING_AREA_CODE,
            candidates,
        )
        if not errors and filter_error is not None:
            errors["base"] = filter_error

        return self.async_show_form(
            step_id="warning",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_options(self, user_input: ConfigFlowInput | None = None):
        """Enter the remaining options and create the entry."""
        errors: dict[str, str] = {}
        default_name = self._entry_data.get(CONF_FORECAST_AREA_NAME, DOMAIN)

        if user_input is not None:
            data, errors = self._normalize_final_form_input(user_input)
            if not str(user_input[CONF_NAME]).strip():
                errors["base"] = "invalid_name"
            elif not errors:
                unique_id = ":".join(
                    (
                        self._entry_data[CONF_FORECAST_AREA_CODE],
                        self._entry_data[CONF_OBSERVATION_STATION_CODE],
                        self._entry_data[CONF_WARNING_AREA_CODE],
                    )
                )
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                entry_data = {
                    **self._entry_data,
                    **data,
                }
                entry_data.pop(CONF_REGION_CODE, None)
                return self.async_create_entry(
                    title=entry_data[CONF_NAME],
                    data=entry_data,
                )

        return self.async_show_form(
            step_id="options",
            data_schema=self._build_final_options_schema(default_name=default_name),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(
        entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow handler."""
        return HaWeatherJmaOptionsFlow(entry)

    def _build_final_options_schema(self, *, default_name: str) -> vol.Schema:
        return build_options_schema(
            default_name=default_name,
            default_update_interval=DEFAULT_UPDATE_INTERVAL_MINUTES,
            default_warning_levels=list(DEFAULT_ENABLED_WARNING_LEVELS),
            default_entity_groups=list(RECOMMENDED_ENABLED_ENTITY_GROUPS),
        )

    def _normalize_final_form_input(
        self,
        user_input: ConfigFlowInput,
    ) -> tuple[ConfigFlowInput, dict[str, str]]:
        errors: dict[str, str] = {}
        enabled_levels = [
            level
            for level in user_input.get(CONF_ENABLED_WARNING_LEVELS, [])
            if level in WARNING_LEVEL_LABELS
        ]
        enabled_entity_groups = [
            group
            for group in user_input.get(CONF_ENABLED_ENTITY_GROUPS, [])
            if group in ENTITY_GROUP_LABELS
        ]
        if (
            ENTITY_GROUP_WARNING_BINARY_SENSORS in enabled_entity_groups
            and not enabled_levels
        ):
            errors["base"] = "invalid_warning_levels"

        return (
            {
                CONF_NAME: str(user_input[CONF_NAME]).strip(),
                CONF_UPDATE_INTERVAL_MINUTES: int(
                    user_input[CONF_UPDATE_INTERVAL_MINUTES]
                ),
                CONF_ENABLED_WARNING_LEVELS: enabled_levels,
                CONF_ENABLED_ENTITY_GROUPS: enabled_entity_groups,
            },
            errors,
        )

    async def _async_get_region_candidates(self) -> dict[str, RegionCandidate]:
        if not self._region_candidates:
            area_data = await self._get_api_client().fetch_area_definitions()
            self._region_candidates = build_region_candidates(area_data)
            self._office_region_codes = {
                office_code: str(office.get("parent") or "")
                for office_code, office in area_data.get("offices", {}).items()
            }
        return self._region_candidates

    async def _async_get_forecast_candidates(self) -> dict[str, ForecastAreaCandidate]:
        region_code = self._entry_data.get(CONF_REGION_CODE)
        if not self._forecast_candidates:
            area_data = await self._get_api_client().fetch_area_definitions()
            if not self._office_region_codes:
                self._office_region_codes = {
                    office_code: str(office.get("parent") or "")
                    for office_code, office in area_data.get("offices", {}).items()
                }
            self._forecast_candidates = build_forecast_area_candidates(area_data)
        if region_code is None:
            return self._forecast_candidates
        return {
            code: candidate
            for code, candidate in self._forecast_candidates.items()
            if self._forecast_belongs_to_region(candidate, str(region_code))
        }

    async def _async_get_station_candidates(
        self,
    ) -> dict[str, ObservationStationCandidate]:
        if not self._station_candidates:
            station_data = await self._get_api_client().fetch_amedas_table()
            self._station_candidates = build_observation_station_candidates(
                station_data
            )
        return self._station_candidates

    async def _async_get_observation_candidates(
        self,
    ) -> dict[str, ObservationStationCandidate]:
        if self._observation_candidates:
            return self._observation_candidates

        station_candidates = await self._async_get_station_candidates()
        forecast_data = await self._async_fetch_forecast_for_validation()
        supported_codes = extract_forecast_observation_station_codes(forecast_data)
        supported_candidates = {
            code: station_candidates[code]
            for code in supported_codes
            if code in station_candidates
        }
        nearby_candidates = self._build_nearby_observation_candidates(
            station_candidates,
            supported_candidates,
        )

        if supported_candidates or nearby_candidates:
            self._observation_candidates = {
                **supported_candidates,
                **nearby_candidates,
            }
        else:
            self._observation_candidates = station_candidates

        return self._observation_candidates

    async def _async_get_warning_candidates(self) -> dict[str, WarningAreaCandidate]:
        if not self._warning_candidates:
            area_data = await self._get_api_client().fetch_area_definitions()
            self._warning_candidates = build_warning_area_candidates(area_data)
        forecast_office_code = self._entry_data.get(CONF_FORECAST_OFFICE_CODE)
        if forecast_office_code is None:
            return self._warning_candidates
        return {
            code: candidate
            for code, candidate in self._warning_candidates.items()
            if candidate.office_code == str(forecast_office_code)
        }

    def _get_api_client(self) -> HaWeatherJmaApiClient:
        if self._api_client is None:
            self._api_client = HaWeatherJmaApiClient(async_get_clientsession(self.hass))
        return self._api_client

    async def _async_fetch_forecast_for_validation(self) -> list[dict[str, Any]]:
        return await self._get_api_client().fetch_forecast(
            self._entry_data[CONF_FORECAST_OFFICE_CODE]
        )

    def _show_connect_error(self, step_id: str):
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema({}),
            errors={"base": "cannot_connect"},
        )

    def _build_candidate_schema(
        self,
        field_name: str,
        candidates: CandidateMap,
    ) -> tuple[vol.Schema, str | None]:
        filter_field = FILTER_FIELD_MAP[field_name]
        filter_value = self._candidate_filters.get(field_name, "")
        filtered_candidates = self._filter_candidates(candidates, filter_value)
        schema_fields: dict[Any, Any] = {
            vol.Optional(filter_field, default=filter_value): str
        }

        error: str | None = None
        if len(filtered_candidates) <= MAX_FILTERED_CANDIDATES:
            schema_fields[vol.Optional(field_name)] = vol.In(
                {key: value.display_label for key, value in filtered_candidates.items()}
            )
        elif filter_value:
            error = "too_many_matches"

        if filter_value and not filtered_candidates:
            error = "no_matching_candidates"

        return vol.Schema(schema_fields), error

    def _update_candidate_filter(
        self,
        field_name: str,
        user_input: ConfigFlowInput | None,
    ) -> None:
        if user_input is None:
            return
        filter_field = FILTER_FIELD_MAP[field_name]
        self._candidate_filters[field_name] = str(
            user_input.get(filter_field, "")
        ).strip()

    def _filter_candidates(
        self,
        candidates: CandidateMap,
        filter_value: str,
    ) -> CandidateMap:
        normalized_filter = self._normalize_search_text(filter_value)
        if not normalized_filter:
            return candidates

        return {
            key: value
            for key, value in candidates.items()
            if normalized_filter in self._candidate_search_text(value)
        }

    def _candidate_search_text(
        self,
        candidate: (
            ForecastAreaCandidate
            | ObservationStationCandidate
            | RegionCandidate
            | WarningAreaCandidate
        ),
    ) -> str:
        parts = [candidate.display_label, candidate.code, candidate.name]
        if isinstance(candidate, ForecastAreaCandidate | WarningAreaCandidate):
            parts.extend((candidate.office_code, candidate.office_name))
        return self._normalize_search_text(" ".join(parts))

    def _forecast_belongs_to_region(
        self,
        candidate: ForecastAreaCandidate,
        region_code: str,
    ) -> bool:
        office_region_code = self._office_region_codes.get(candidate.office_code)
        if office_region_code is None:
            return True
        return office_region_code == region_code

    def _normalize_search_text(self, value: str) -> str:
        return unicodedata.normalize("NFKC", value).casefold().strip()

    def _build_nearby_observation_candidates(
        self,
        all_candidates: Mapping[str, ObservationStationCandidate],
        supported_candidates: Mapping[str, ObservationStationCandidate],
    ) -> dict[str, ObservationStationCandidate]:
        reference_points = [
            candidate
            for candidate in supported_candidates.values()
            if candidate.latitude is not None and candidate.longitude is not None
        ]
        if not reference_points:
            return {}

        nearby_candidates: list[tuple[float, str, ObservationStationCandidate]] = []
        for code, candidate in all_candidates.items():
            if code in supported_candidates:
                continue
            if candidate.latitude is None or candidate.longitude is None:
                continue

            typed_reference_points = [
                (reference.latitude, reference.longitude)
                for reference in reference_points
                if reference.latitude is not None and reference.longitude is not None
            ]
            distance_km = min(
                self._distance_km(
                    candidate.latitude,
                    candidate.longitude,
                    reference_latitude,
                    reference_longitude,
                )
                for reference_latitude, reference_longitude in typed_reference_points
            )
            if distance_km <= NEARBY_OBSERVATION_DISTANCE_KM:
                nearby_candidates.append((distance_km, code, candidate))

        nearby_candidates.sort(
            key=lambda item: (item[0], item[2].name.casefold(), item[1])
        )
        return {
            code: candidate
            for _, code, candidate in nearby_candidates[
                :MAX_NEARBY_OBSERVATION_CANDIDATES
            ]
        }

    def _distance_km(
        self,
        latitude_1: float,
        longitude_1: float,
        latitude_2: float,
        longitude_2: float,
    ) -> float:
        lat_1 = math.radians(latitude_1)
        lon_1 = math.radians(longitude_1)
        lat_2 = math.radians(latitude_2)
        lon_2 = math.radians(longitude_2)
        delta_lat = lat_2 - lat_1
        delta_lon = lon_2 - lon_1
        haversine = (
            math.sin(delta_lat / 2.0) ** 2
            + math.cos(lat_1) * math.cos(lat_2) * math.sin(delta_lon / 2.0) ** 2
        )
        return (
            6371.0
            * 2.0
            * math.atan2(
                haversine**0.5,
                (1.0 - haversine) ** 0.5,
            )
        )


class HaWeatherJmaOptionsFlow(config_entries.OptionsFlow):
    """Options flow for ha-weather-jma."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(self, user_input: ConfigFlowInput | None = None):
        """Manage integration options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            data, errors = HaWeatherJmaConfigFlow()._normalize_final_form_input(
                {
                    **user_input,
                    CONF_NAME: self._entry.title,
                }
            )
            if not errors:
                data.pop(CONF_NAME, None)
                return self.async_create_entry(title="", data=data)

        current = {**self._entry.data, **self._entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=build_options_schema(
                default_update_interval=int(
                    current.get(
                        CONF_UPDATE_INTERVAL_MINUTES,
                        DEFAULT_UPDATE_INTERVAL_MINUTES,
                    )
                ),
                default_warning_levels=list(
                    current.get(
                        CONF_ENABLED_WARNING_LEVELS,
                        DEFAULT_ENABLED_WARNING_LEVELS,
                    )
                ),
                default_entity_groups=list(
                    current.get(
                        CONF_ENABLED_ENTITY_GROUPS,
                        DEFAULT_ENABLED_ENTITY_GROUPS,
                    )
                ),
            ),
            errors=errors,
        )
