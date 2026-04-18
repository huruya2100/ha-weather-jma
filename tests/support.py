"""Shared test support for ha-weather-jma."""

# mypy: disable-error-code=attr-defined

from __future__ import annotations

import importlib.util
import json
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_ROOT = ROOT / "custom_components" / "ha_weather_jma"
FIXTURE_ROOT = ROOT / "tests" / "fixtures"

MODULE_LOAD_ORDER = (
    "const",
    "parser",
    "api",
    "coordinator",
    "entity",
    "weather",
    "sensor",
    "binary_sensor",
    "config_flow",
)

MODULE_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "const": (),
    "parser": ("const",),
    "api": ("const",),
    "coordinator": ("api", "const", "parser"),
    "entity": ("const", "coordinator", "parser"),
    "weather": ("const", "coordinator", "entity", "parser"),
    "sensor": ("const", "coordinator", "entity", "parser"),
    "binary_sensor": ("const", "coordinator", "entity", "parser"),
    "config_flow": ("api", "const", "parser"),
}


def read_fixture(name: str) -> Any:
    """Read a JSON fixture."""
    with (FIXTURE_ROOT / name).open(encoding="utf-8") as fixture_file:
        return json.load(fixture_file)


def read_text_fixture(name: str) -> str:
    """Read a text fixture."""
    return (FIXTURE_ROOT / name).read_text(encoding="utf-8")


def clear_stubbed_modules() -> None:
    """Remove stubbed imports so tests can start cleanly."""
    for module_name in list(sys.modules):
        if (
            module_name == "aiohttp"
            or module_name.startswith("homeassistant")
            or module_name == "custom_components"
            or module_name.startswith("custom_components.ha_weather_jma")
        ):
            sys.modules.pop(module_name, None)


def load_modules(*module_names: str) -> dict[str, Any]:
    """Load integration modules with minimal Home Assistant stubs."""
    clear_stubbed_modules()
    _install_package_stubs()

    required = set(module_names)
    pending = list(module_names)
    while pending:
        current = pending.pop()
        for dependency in MODULE_DEPENDENCIES[current]:
            if dependency not in required:
                required.add(dependency)
                pending.append(dependency)

    loaded: dict[str, Any] = {}
    for module_name in MODULE_LOAD_ORDER:
        if module_name not in required:
            continue
        loaded[module_name] = _load_module(module_name)
    return loaded


def get_stub_module(module_name: str) -> types.ModuleType:
    """Return a stubbed module."""
    return sys.modules[module_name]


def _load_module(module_name: str):
    qualified_name = f"custom_components.ha_weather_jma.{module_name}"
    spec = importlib.util.spec_from_file_location(
        qualified_name,
        INTEGRATION_ROOT / f"{module_name}.py",
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load module spec for {qualified_name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified_name] = module
    spec.loader.exec_module(module)
    return module


def _install_package_stubs() -> None:
    custom_components = types.ModuleType("custom_components")
    custom_components.__path__ = [str(INTEGRATION_ROOT.parent)]
    sys.modules["custom_components"] = custom_components

    package = types.ModuleType("custom_components.ha_weather_jma")
    package.__path__ = [str(INTEGRATION_ROOT)]
    sys.modules["custom_components.ha_weather_jma"] = package

    _install_aiohttp_stub()
    _install_homeassistant_stubs()


def _install_aiohttp_stub() -> None:
    aiohttp = types.ModuleType("aiohttp")

    class ClientError(Exception):
        """Base aiohttp error."""

    class ClientConnectionError(ClientError):
        """Connection error."""

    class ClientResponseError(ClientError):
        """Response error with status."""

        def __init__(self, *, status: int = 0) -> None:
            super().__init__(status)
            self.status = status

    class ContentTypeError(ClientResponseError):
        """Content type error."""

    class ClientSession:
        """Placeholder client session."""

    aiohttp.ClientError = ClientError
    aiohttp.ClientConnectionError = ClientConnectionError
    aiohttp.ClientResponseError = ClientResponseError
    aiohttp.ContentTypeError = ContentTypeError
    aiohttp.ClientSession = ClientSession
    sys.modules["aiohttp"] = aiohttp


def _install_homeassistant_stubs() -> None:
    homeassistant = types.ModuleType("homeassistant")
    sys.modules["homeassistant"] = homeassistant

    const_module = types.ModuleType("homeassistant.const")

    class Platform:
        WEATHER = "weather"
        SENSOR = "sensor"
        BINARY_SENSOR = "binary_sensor"

    class UnitOfPressure:
        HPA = "hPa"

    class UnitOfSpeed:
        METERS_PER_SECOND = "m/s"

    class UnitOfTemperature:
        CELSIUS = "C"

    const_module.Platform = Platform
    const_module.UnitOfPressure = UnitOfPressure
    const_module.UnitOfSpeed = UnitOfSpeed
    const_module.UnitOfTemperature = UnitOfTemperature
    const_module.PERCENTAGE = "%"
    sys.modules["homeassistant.const"] = const_module
    homeassistant.const = const_module

    core_module = types.ModuleType("homeassistant.core")

    class HomeAssistant:
        """Minimal Home Assistant stub."""

        def __init__(self) -> None:
            self.data: dict[str, Any] = {}
            self.config_entries = types.SimpleNamespace(
                async_forward_entry_setups=_async_return_true,
                async_reload=_async_return_true,
                async_unload_platforms=_async_return_true,
            )

        def async_create_task(self, coro: Any) -> Any:
            return coro

    def callback(func):
        return func

    core_module.HomeAssistant = HomeAssistant
    core_module.callback = callback
    sys.modules["homeassistant.core"] = core_module
    homeassistant.core = core_module

    config_entries_module = types.ModuleType("homeassistant.config_entries")

    @dataclass(slots=True)
    class ConfigEntry:
        entry_id: str
        title: str
        data: dict[str, Any]
        options: dict[str, Any] | None = None

        def __post_init__(self) -> None:
            if self.options is None:
                self.options = {}

        def add_update_listener(self, listener):
            return listener

        def async_on_unload(self, listener) -> None:
            del listener

    class AbortFlow(Exception):
        """Raised when a flow is aborted."""

    class ConfigFlow:
        """Minimal ConfigFlow stub."""

        _configured_unique_ids: set[str] = set()

        def __init_subclass__(cls, **kwargs: Any) -> None:
            super().__init_subclass__()

        def __init__(self) -> None:
            self.hass = None
            self._unique_id: str | None = None

        async def async_set_unique_id(self, unique_id: str) -> None:
            self._unique_id = unique_id

        def _abort_if_unique_id_configured(self) -> None:
            if self._unique_id in self._configured_unique_ids:
                raise AbortFlow(self._unique_id)

        def async_show_form(
            self,
            *,
            step_id: str,
            data_schema: Any,
            errors: dict[str, str] | None = None,
        ) -> dict[str, Any]:
            return {
                "type": "form",
                "step_id": step_id,
                "data_schema": data_schema,
                "errors": errors or {},
            }

        def async_create_entry(
            self,
            *,
            title: str,
            data: dict[str, Any],
        ) -> dict[str, Any]:
            return {
                "type": "create_entry",
                "title": title,
                "data": data,
            }

    class OptionsFlow:
        """Minimal OptionsFlow stub."""

        def async_show_form(
            self,
            *,
            step_id: str,
            data_schema: Any,
            errors: dict[str, str] | None = None,
        ) -> dict[str, Any]:
            return {
                "type": "form",
                "step_id": step_id,
                "data_schema": data_schema,
                "errors": errors or {},
            }

        def async_create_entry(
            self,
            *,
            title: str,
            data: dict[str, Any],
        ) -> dict[str, Any]:
            return {
                "type": "create_entry",
                "title": title,
                "data": data,
            }

    config_entries_module.AbortFlow = AbortFlow
    config_entries_module.ConfigEntry = ConfigEntry
    config_entries_module.ConfigFlow = ConfigFlow
    config_entries_module.OptionsFlow = OptionsFlow
    sys.modules["homeassistant.config_entries"] = config_entries_module
    homeassistant.config_entries = config_entries_module

    helpers_module = types.ModuleType("homeassistant.helpers")
    sys.modules["homeassistant.helpers"] = helpers_module
    homeassistant.helpers = helpers_module

    aiohttp_client_module = types.ModuleType("homeassistant.helpers.aiohttp_client")
    aiohttp_client_module.async_get_clientsession = lambda hass: object()
    sys.modules["homeassistant.helpers.aiohttp_client"] = aiohttp_client_module
    helpers_module.aiohttp_client = aiohttp_client_module

    config_validation_module = types.ModuleType(
        "homeassistant.helpers.config_validation"
    )
    config_validation_module.multi_select = lambda options: (lambda value: value)
    sys.modules["homeassistant.helpers.config_validation"] = config_validation_module
    helpers_module.config_validation = config_validation_module

    update_coordinator_module = types.ModuleType(
        "homeassistant.helpers.update_coordinator"
    )

    class UpdateFailed(Exception):
        """Coordinator update failure."""

    class DataUpdateCoordinator:
        """Minimal coordinator base class."""

        def __class_getitem__(cls, item):
            return cls

        def __init__(
            self,
            hass: HomeAssistant,
            logger: Any,
            *,
            name: str,
            update_interval: Any = None,
        ) -> None:
            self.hass = hass
            self.logger = logger
            self.name = name
            self.update_interval = update_interval
            self.data = None

        async def async_config_entry_first_refresh(self) -> None:
            self.data = await self._async_update_data()

    class CoordinatorEntity:
        """Minimal coordinator-backed entity."""

        def __class_getitem__(cls, item):
            return cls

        def __init__(self, coordinator: Any) -> None:
            self.coordinator = coordinator
            self.hass = getattr(coordinator, "hass", None)

        def _handle_coordinator_update(self) -> None:
            return None

    update_coordinator_module.UpdateFailed = UpdateFailed
    update_coordinator_module.DataUpdateCoordinator = DataUpdateCoordinator
    update_coordinator_module.CoordinatorEntity = CoordinatorEntity
    sys.modules["homeassistant.helpers.update_coordinator"] = update_coordinator_module
    helpers_module.update_coordinator = update_coordinator_module

    device_registry_module = types.ModuleType("homeassistant.helpers.device_registry")

    class DeviceEntryType:
        SERVICE = "service"

    class DeviceInfo(dict):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)

    device_registry_module.DeviceEntryType = DeviceEntryType
    device_registry_module.DeviceInfo = DeviceInfo
    sys.modules["homeassistant.helpers.device_registry"] = device_registry_module
    helpers_module.device_registry = device_registry_module

    entity_module = types.ModuleType("homeassistant.helpers.entity")
    entity_module.async_generate_entity_id = (
        lambda fmt, object_id, hass=None: fmt.format(object_id)
    )
    sys.modules["homeassistant.helpers.entity"] = entity_module
    helpers_module.entity = entity_module

    entity_platform_module = types.ModuleType("homeassistant.helpers.entity_platform")
    entity_platform_module.AddEntitiesCallback = object
    sys.modules["homeassistant.helpers.entity_platform"] = entity_platform_module
    helpers_module.entity_platform = entity_platform_module

    components_module = types.ModuleType("homeassistant.components")
    sys.modules["homeassistant.components"] = components_module
    homeassistant.components = components_module

    weather_module = types.ModuleType("homeassistant.components.weather")

    class WeatherEntity:
        async def async_update_listeners(self) -> None:
            return None

    class WeatherEntityFeature:
        FORECAST_DAILY = 1

    weather_module.WeatherEntity = WeatherEntity
    weather_module.WeatherEntityFeature = WeatherEntityFeature
    sys.modules["homeassistant.components.weather"] = weather_module
    components_module.weather = weather_module

    sensor_module = types.ModuleType("homeassistant.components.sensor")

    class SensorEntity:
        pass

    @dataclass(slots=True, frozen=True, kw_only=True)
    class SensorEntityDescription:
        key: str | None = None
        translation_key: str | None = None
        device_class: Any | None = None
        native_unit_of_measurement: Any | None = None

    class SensorDeviceClass:
        TIMESTAMP = "timestamp"

    sensor_module.SensorEntity = SensorEntity
    sensor_module.SensorEntityDescription = SensorEntityDescription
    sensor_module.SensorDeviceClass = SensorDeviceClass
    sys.modules["homeassistant.components.sensor"] = sensor_module
    components_module.sensor = sensor_module

    binary_sensor_module = types.ModuleType("homeassistant.components.binary_sensor")

    class BinarySensorEntity:
        pass

    class BinarySensorDeviceClass:
        SAFETY = "safety"

    binary_sensor_module.BinarySensorEntity = BinarySensorEntity
    binary_sensor_module.BinarySensorDeviceClass = BinarySensorDeviceClass
    sys.modules["homeassistant.components.binary_sensor"] = binary_sensor_module
    components_module.binary_sensor = binary_sensor_module


async def _async_return_true(*args: Any, **kwargs: Any) -> bool:
    return True
