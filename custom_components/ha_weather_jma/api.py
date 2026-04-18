"""API client for ha-weather-jma."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from http import HTTPStatus
from time import monotonic
from typing import Any, Awaitable, Callable
from xml.etree import ElementTree as ET

import aiohttp

from .const import (
    AMEDAS_LATEST_TIME_URL,
    AMEDAS_MAP_URL,
    AMEDAS_TABLE_URL,
    AREA_URL,
    DEFINITION_CACHE_TTL_SECONDS,
    FORECAST_URL,
    HTTP_RETRY_BACKOFF_BASE_SECONDS,
    HTTP_RETRY_COUNT,
    HTTP_TIMEOUT_SECONDS,
    WARNING_XML_FEED_LONG_URL,
    WARNING_XML_FEED_SHORT_URL,
)

_LOGGER = logging.getLogger(__name__)


class HaWeatherJmaApiClient:
    """Thin HTTP client for JMA endpoints.

    Forecast and observation data come from JMA JSON endpoints.
    Warning data is resolved from the public JMAXML Atom feeds.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        timeout_seconds: int = HTTP_TIMEOUT_SECONDS,
        retries: int = HTTP_RETRY_COUNT,
        retry_backoff_base_seconds: float = HTTP_RETRY_BACKOFF_BASE_SECONDS,
    ) -> None:
        self._session = session
        self._timeout_seconds = timeout_seconds
        self._retries = retries
        self._retry_backoff_base_seconds = retry_backoff_base_seconds
        self._cache: dict[str, tuple[float, Any]] = {}
        self._warning_xml_urls: dict[str, dict[str, str]] = {}

    async def fetch_area_definitions(self) -> dict[str, Any]:
        """Fetch and cache area.json."""
        return await self._async_fetch_cached_json("area", AREA_URL)

    async def fetch_amedas_table(self) -> dict[str, Any]:
        """Fetch and cache amedastable.json."""
        return await self._async_fetch_cached_json("amedas_table", AMEDAS_TABLE_URL)

    async def fetch_amedas_latest_time(self) -> str:
        """Fetch the latest AMeDAS timestamp."""
        return await self._async_fetch_text(AMEDAS_LATEST_TIME_URL)

    async def fetch_amedas_observation(
        self,
        station_code: str,
        observed_at: str,
    ) -> dict[str, Any]:
        """Fetch the latest map payload and return a single station record."""
        timestamp = (
            observed_at.strip()
            .replace("-", "")
            .replace(":", "")
            .replace("T", "")
            .split("+", maxsplit=1)[0]
            .split("Z", maxsplit=1)[0]
        )
        payload = await self._async_fetch_json(
            AMEDAS_MAP_URL.format(timestamp=timestamp)
        )
        if not isinstance(payload, Mapping):
            raise ValueError("Unexpected AMeDAS map payload")
        station = payload.get(station_code)
        if not isinstance(station, Mapping):
            raise LookupError(f"Station {station_code} not found in AMeDAS payload")
        return dict(station)

    async def fetch_forecast(self, office_code: str) -> list[dict[str, Any]]:
        """Fetch forecast JSON."""
        payload = await self._async_fetch_json(
            FORECAST_URL.format(office_code=office_code)
        )
        if not isinstance(payload, list):
            raise ValueError("Unexpected forecast payload")
        return payload

    async def fetch_warning_xml_documents(self, office_code: str) -> list[str]:
        """Fetch the latest warning XML documents for one office.

        This is the warning-source entrypoint used at runtime.
        """
        urls = await self._async_resolve_warning_xml_urls(office_code)
        documents, failed_product_ids = await self._async_fetch_warning_documents(urls)
        if failed_product_ids:
            self._drop_warning_xml_urls(office_code, failed_product_ids)
            refreshed_urls = await self._async_refresh_warning_xml_urls(office_code)
            retry_urls = (
                dict(refreshed_urls)
                if not documents
                else {
                    product_id: refreshed_urls[product_id]
                    for product_id in failed_product_ids
                    if product_id in refreshed_urls
                }
            )
            if retry_urls:
                retry_documents, still_failed_product_ids = (
                    await self._async_fetch_warning_documents(retry_urls)
                )
                documents.extend(retry_documents)
                if still_failed_product_ids:
                    self._drop_warning_xml_urls(office_code, still_failed_product_ids)

        if documents:
            return documents
        raise LookupError(f"No warning XML documents found for {office_code}")

    async def _async_fetch_cached_json(
        self, cache_key: str, url: str
    ) -> dict[str, Any]:
        cached = self._cache.get(cache_key)
        now = monotonic()
        if cached and (now - cached[0]) < DEFINITION_CACHE_TTL_SECONDS:
            return cached[1]
        payload = await self._async_fetch_json(url)
        if not isinstance(payload, Mapping):
            raise ValueError(f"Unexpected definition payload for {url}")
        result = dict(payload)
        self._cache[cache_key] = (now, result)
        return result

    async def _async_fetch_json(self, url: str) -> Any:
        return await self._async_fetch_with_retry(url, lambda response: response.json())

    async def _async_fetch_text(self, url: str) -> str:
        return await self._async_fetch_with_retry(url, lambda response: response.text())

    async def _async_fetch_with_retry(
        self,
        url: str,
        reader: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        """Fetch a response body using the shared retry policy."""
        for attempt in range(self._retries + 1):
            try:
                async with asyncio.timeout(self._timeout_seconds):
                    async with self._session.get(url) as response:
                        response.raise_for_status()
                        payload = await reader(response)
                        return payload.strip() if isinstance(payload, str) else payload
            except aiohttp.ClientResponseError as err:
                if self._should_retry(attempt, err.status):
                    await self._async_sleep_before_retry(attempt)
                    _LOGGER.debug(
                        "Retrying JMA API fetch for %s after HTTP %s (%s/%s)",
                        url,
                        err.status,
                        attempt + 1,
                        self._retries + 1,
                    )
                    continue
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                if attempt < self._retries:
                    await self._async_sleep_before_retry(attempt)
                    _LOGGER.debug(
                        "Retrying JMA API fetch for %s after %s (%s/%s)",
                        url,
                        err.__class__.__name__,
                        attempt + 1,
                        self._retries + 1,
                    )
                    continue
                raise

    async def _async_sleep_before_retry(self, attempt: int) -> None:
        """Apply exponential backoff before the next retry attempt."""
        await asyncio.sleep(self._retry_backoff_base_seconds * (2**attempt))

    def _should_retry(self, attempt: int, status: int) -> bool:
        """Return whether a response failure should be retried."""
        return attempt < self._retries and (
            status >= HTTPStatus.INTERNAL_SERVER_ERROR
            or status in {HTTPStatus.NOT_FOUND, HTTPStatus.REQUEST_TIMEOUT}
            or status == HTTPStatus.TOO_MANY_REQUESTS
        )

    async def _async_resolve_warning_xml_urls(
        self,
        office_code: str,
    ) -> dict[str, str]:
        """Resolve the latest warning XML URLs for one office from Atom feeds."""
        cached = dict(self._warning_xml_urls.get(office_code, {}))
        latest = await self._async_find_warning_xml_urls_in_feed(
            WARNING_XML_FEED_SHORT_URL,
            office_code,
        )
        if latest:
            cached.update(latest)
            self._warning_xml_urls[office_code] = cached
            return cached
        if cached:
            return cached

        cached = await self._async_find_warning_xml_urls_in_feed(
            WARNING_XML_FEED_LONG_URL,
            office_code,
        )
        if not cached:
            raise LookupError(f"No warning XML URLs found for {office_code}")
        self._warning_xml_urls[office_code] = cached
        return cached

    async def _async_refresh_warning_xml_urls(self, office_code: str) -> dict[str, str]:
        """Refresh warning XML URLs from feeds and drop stale cached entries."""
        latest = await self._async_find_warning_xml_urls_in_feed(
            WARNING_XML_FEED_SHORT_URL,
            office_code,
        )
        fallback = await self._async_find_warning_xml_urls_in_feed(
            WARNING_XML_FEED_LONG_URL,
            office_code,
        )
        refreshed = dict(fallback)
        refreshed.update(latest)
        if not refreshed:
            raise LookupError(f"No warning XML URLs found for {office_code}")
        self._warning_xml_urls[office_code] = refreshed
        return refreshed

    async def _async_find_warning_xml_urls_in_feed(
        self,
        feed_url: str,
        office_code: str,
    ) -> dict[str, str]:
        feed_text = await self._async_fetch_text(feed_url)
        try:
            root = ET.fromstring(feed_text)
        except ET.ParseError as err:
            raise ValueError(f"Unexpected warning feed XML: {feed_url}") from err

        urls: dict[str, str] = {}
        for entry in root.findall("{http://www.w3.org/2005/Atom}entry"):
            link = entry.find("{http://www.w3.org/2005/Atom}link")
            href = link.get("href") if link is not None else None
            if href is None:
                continue
            product_id = self._warning_xml_product_id(href)
            if product_id is None or product_id in urls:
                continue
            if not href.endswith(f"_{office_code}.xml"):
                continue
            urls[product_id] = href
        return urls

    def _warning_xml_product_id(self, href: str) -> str | None:
        """Return the supported warning product id from an XML document URL."""
        filename = href.rsplit("/", maxsplit=1)[-1]
        segments = filename.removesuffix(".xml").split("_")
        if len(segments) < 4:
            return None
        product_id = segments[-2]
        if product_id == "VPWW54":
            return None
        if product_id == "VPWW53":
            return product_id
        if product_id.startswith("VPWW") and product_id[4:].isdigit():
            suffix = int(product_id[4:])
            if 55 <= suffix <= 61:
                return product_id
        return None

    async def _async_fetch_warning_documents(
        self,
        urls: Mapping[str, str],
    ) -> tuple[list[str], set[str]]:
        """Fetch warning XML documents in parallel and report per-product failures."""
        product_ids = list(urls)
        results = await asyncio.gather(
            *(self._async_fetch_text(urls[product_id]) for product_id in product_ids),
            return_exceptions=True,
        )

        documents: list[str] = []
        failed_product_ids: set[str] = set()
        for product_id, result in zip(product_ids, results, strict=False):
            if isinstance(result, BaseException):
                failed_product_ids.add(product_id)
                _LOGGER.warning(
                    "Warning XML fetch failed for %s: %s",
                    product_id,
                    result,
                )
                continue
            documents.append(result)

        return documents, failed_product_ids

    def _drop_warning_xml_urls(
        self,
        office_code: str,
        product_ids: set[str],
    ) -> None:
        """Remove failed warning XML URLs from the office cache."""
        cached = self._warning_xml_urls.get(office_code)
        if not cached:
            return
        for product_id in product_ids:
            cached.pop(product_id, None)
        if cached:
            self._warning_xml_urls[office_code] = cached
            return
        self._warning_xml_urls.pop(office_code, None)
