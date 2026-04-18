"""Live network tests for ha-weather-jma warning XML fetch and parsing."""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import sys
import types
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_ROOT = ROOT / "custom_components" / "ha_weather_jma"
LIVE_PACKAGE_NAME = "_live_ha_weather_jma"
ATOM_NAMESPACE = {"atom": "http://www.w3.org/2005/Atom"}
SUPPORTED_WARNING_PRODUCTS = {
    "VPWW53",
    "VPWW55",
    "VPWW56",
    "VPWW57",
    "VPWW58",
    "VPWW59",
    "VPWW60",
    "VPWW61",
}


@pytest.fixture(scope="module")
def live_modules():
    """Load integration modules without Home Assistant/aiohttp stubs."""
    sys.modules.pop("aiohttp", None)
    importlib.invalidate_caches()
    aiohttp = pytest.importorskip("aiohttp")

    for module_name in list(sys.modules):
        if module_name == LIVE_PACKAGE_NAME or module_name.startswith(
            f"{LIVE_PACKAGE_NAME}."
        ):
            sys.modules.pop(module_name, None)

    package = types.ModuleType(LIVE_PACKAGE_NAME)
    package.__path__ = [str(INTEGRATION_ROOT)]
    sys.modules[LIVE_PACKAGE_NAME] = package

    def _load_module(module_name: str):
        qualified_name = f"{LIVE_PACKAGE_NAME}.{module_name}"
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

    return {
        "aiohttp": aiohttp,
        "const": _load_module("const"),
        "api": _load_module("api"),
        "parser": _load_module("parser"),
    }


async def _fetch_text(session, url: str) -> str:
    async with session.get(url) as response:
        response.raise_for_status()
        return (await response.text()).strip()


def _warning_entries_from_feed(feed_text: str) -> list[dict[str, str]]:
    root = ET.fromstring(feed_text)
    entries: list[dict[str, str]] = []
    for entry in root.findall("atom:entry", ATOM_NAMESPACE):
        link = entry.find("atom:link", ATOM_NAMESPACE)
        href = link.get("href") if link is not None else None
        if href is None:
            continue
        filename = href.rsplit("/", maxsplit=1)[-1]
        segments = filename.removesuffix(".xml").split("_")
        if len(segments) < 4:
            continue
        product_id = segments[-2]
        if product_id not in SUPPORTED_WARNING_PRODUCTS:
            continue
        entries.append(
            {
                "href": href,
                "office_code": segments[-1],
                "product_id": product_id,
            }
        )
    return entries


async def _discover_live_warning_entry(const, session) -> dict[str, str]:
    for feed_url in (
        const.WARNING_XML_FEED_SHORT_URL,
        const.WARNING_XML_FEED_LONG_URL,
    ):
        entries = _warning_entries_from_feed(await _fetch_text(session, feed_url))
        if entries:
            return entries[0]
    raise pytest.skip.Exception("No live warning XML entries found in JMA feeds")


def _extract_first_municipal_area(document: str) -> tuple[str, str]:
    root = ET.fromstring(document)
    for item in root.findall(
        ".//{*}Body/{*}Warning[@type='気象警報・注意報（市町村等）']/{*}Item"
    ):
        area = item.find("./{*}Area")
        if area is None:
            continue
        area_code = area.findtext("./{*}Code")
        area_name = area.findtext("./{*}Name")
        if area_code and area_name:
            return area_code, area_name
    raise pytest.skip.Exception("Live warning XML did not contain municipal areas")


@pytest.mark.live
def test_fetch_warning_xml_documents_returns_live_documents(live_modules) -> None:
    """Fetch live warning XML via HaWeatherJmaApiClient with a real HTTP session."""
    aiohttp = live_modules["aiohttp"]
    api = live_modules["api"]
    const = live_modules["const"]

    async def run() -> tuple[dict[str, str], list[str]]:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            entry = await _discover_live_warning_entry(const, session)
            client = api.HaWeatherJmaApiClient(session)
            documents = await client.fetch_warning_xml_documents(entry["office_code"])
            return entry, documents

    entry, documents = asyncio.run(run())

    assert entry["office_code"]
    assert documents
    assert all("<Report" in document for document in documents)


@pytest.mark.live
def test_parse_alerts_xml_handles_live_warning_document(live_modules) -> None:
    """Parse a live warning XML document without relying on the API client."""
    aiohttp = live_modules["aiohttp"]
    const = live_modules["const"]
    parser = live_modules["parser"]

    async def run() -> str:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            entry = await _discover_live_warning_entry(const, session)
            return await _fetch_text(session, entry["href"])

    document = asyncio.run(run())
    area_code, area_name = _extract_first_municipal_area(document)

    alerts = parser.parse_alerts_xml([document], area_code, area_name)
    summary = parser.build_alert_summary(alerts)

    assert len(alerts) == len(const.WARNING_ENTITY_TITLES)
    assert all(item.area_code == area_code for item in alerts.values())
    assert all(item.area_name == area_name for item in alerts.values())
    assert all(item.is_active is not None for item in alerts.values())
    assert summary.report_datetime is not None
    assert summary.publishing_office
    assert summary.max_level in {"none", *const.WARNING_LEVELS}
