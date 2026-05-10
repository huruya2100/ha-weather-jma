"""気象庁の公開エンドポイントへアクセスする非同期 API クライアント。"""

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
    """気象庁データ取得を担当する薄い HTTP クライアント。

    予報・観測は JMA の JSON エンドポイントから取得し、警報は JMAXML の
    Atom フィードから対象 XML 文書の URL を解決して取得します。このクラスは
    Home Assistant には依存せず、通信、リトライ、定義データのキャッシュだけを
    受け持ちます。
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
        """地域・予報区・警報区域の定義 `area.json` を取得してキャッシュします。"""
        return await self._async_fetch_cached_json("area", AREA_URL)

    async def fetch_amedas_table(self) -> dict[str, Any]:
        """アメダス観測所定義 `amedastable.json` を取得してキャッシュします。"""
        return await self._async_fetch_cached_json("amedas_table", AMEDAS_TABLE_URL)

    async def fetch_amedas_latest_time(self) -> str:
        """アメダス観測データの最新タイムスタンプ文字列を取得します。"""
        return await self._async_fetch_text(AMEDAS_LATEST_TIME_URL)

    async def fetch_amedas_observation(
        self,
        station_code: str,
        observed_at: str,
    ) -> dict[str, Any]:
        """指定観測所のアメダス観測値だけを最新 map ペイロードから取り出します。"""
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
        """府県予報区コードに対応する天気予報 JSON を取得します。"""
        payload = await self._async_fetch_json(
            FORECAST_URL.format(office_code=office_code)
        )
        if not isinstance(payload, list):
            raise ValueError("Unexpected forecast payload")
        return payload

    async def fetch_warning_xml_documents(self, office_code: str) -> list[str]:
        """指定官署の最新警報 XML 文書を取得します。

        通常は短期フィードを優先し、キャッシュ済み URL が期限切れや 404 になった
        場合はフィードを再解決して再取得します。警報処理の実行時入口です。
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
        """定義系 JSON を TTL 付きでメモリキャッシュして取得します。"""
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
        """共通リトライ処理を通して JSON レスポンスを取得します。"""
        return await self._async_fetch_with_retry(url, lambda response: response.json())

    async def _async_fetch_text(self, url: str) -> str:
        """共通リトライ処理を通してテキストレスポンスを取得します。"""
        return await self._async_fetch_with_retry(url, lambda response: response.text())

    async def _async_fetch_with_retry(
        self,
        url: str,
        reader: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        """HTTP レスポンス本文を共通リトライポリシーで取得します。"""
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
        """次のリトライまで指数バックオフで待機します。"""
        await asyncio.sleep(self._retry_backoff_base_seconds * (2**attempt))

    def _should_retry(self, attempt: int, status: int) -> bool:
        """HTTP ステータスと試行回数から再試行すべきか判定します。"""
        return attempt < self._retries and (
            status >= HTTPStatus.INTERNAL_SERVER_ERROR
            or status in {HTTPStatus.NOT_FOUND, HTTPStatus.REQUEST_TIMEOUT}
            or status == HTTPStatus.TOO_MANY_REQUESTS
        )

    async def _async_resolve_warning_xml_urls(
        self,
        office_code: str,
    ) -> dict[str, str]:
        """Atom フィードから指定官署の最新警報 XML URL を解決します。"""
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
        """警報 XML URL をフィードから再解決し、古いキャッシュを置き換えます。"""
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
        """1 つの Atom フィードから対応官署・対応プロダクトの XML URL を抽出します。"""
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
        """XML 文書 URL からこの統合が扱う警報プロダクト ID を取り出します。"""
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
        """警報 XML を並列取得し、失敗したプロダクト ID を呼び出し元へ返します。"""
        product_ids = list(urls)
        results = await asyncio.gather(
            *(self._async_fetch_text(urls[product_id]) for product_id in product_ids),
            return_exceptions=True,
        )

        documents: list[str] = []
        failed_product_ids: set[str] = set()
        for product_id, result in zip(product_ids, results, strict=False):
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, Exception):
                failed_product_ids.add(product_id)
                _LOGGER.warning(
                    "Warning XML fetch failed for %s: %s",
                    product_id,
                    result,
                )
                continue
            if isinstance(result, BaseException):
                raise result
            documents.append(result)

        return documents, failed_product_ids

    def _drop_warning_xml_urls(
        self,
        office_code: str,
        product_ids: set[str],
    ) -> None:
        """取得に失敗した警報 XML URL を官署別キャッシュから削除します。"""
        cached = self._warning_xml_urls.get(office_code)
        if not cached:
            return
        for product_id in product_ids:
            cached.pop(product_id, None)
        if cached:
            self._warning_xml_urls[office_code] = cached
            return
        self._warning_xml_urls.pop(office_code, None)
