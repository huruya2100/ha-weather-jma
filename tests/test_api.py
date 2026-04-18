"""API client regression tests."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from tests import support as SUPPORT

LOADED = SUPPORT.load_modules("api")
API = LOADED["api"]
AIOHTTP = SUPPORT.get_stub_module("aiohttp")

OFFICE_CODE = "130000"
SHORT_FEED_URL = "https://www.data.jma.go.jp/developer/xml/feed/extra.xml"
LONG_FEED_URL = "https://www.data.jma.go.jp/developer/xml/feed/extra_l.xml"
STALE_URL_53 = "https://example.invalid/20260414_120000_VPWW53_130000.xml"
STALE_URL_55 = "https://example.invalid/20260414_120000_VPWW55_130000.xml"
FRESH_URL_53 = "https://example.invalid/20260415_120000_VPWW53_130000.xml"
FRESH_URL_55 = "https://example.invalid/20260415_120000_VPWW55_130000.xml"


def build_feed(*urls: str) -> str:
    """Build a minimal Atom feed payload."""
    entries = "".join(f'<entry><link href="{url}" /></entry>' for url in urls)
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<feed xmlns='http://www.w3.org/2005/Atom'>"
        f"{entries}"
        "</feed>"
    )


class FakeResponse:
    """Minimal async response stub."""

    def __init__(self, payload) -> None:
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def raise_for_status(self) -> None:
        if isinstance(self._payload, Exception):
            raise self._payload

    async def text(self) -> str:
        if isinstance(self._payload, Exception):
            raise self._payload
        return str(self._payload)

    async def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    """Session stub returning preconfigured responses."""

    def __init__(self, responses: dict[str, list[object]]) -> None:
        self._responses = {url: list(items) for url, items in responses.items()}

    def get(self, url: str) -> FakeResponse:
        payloads = self._responses.get(url)
        if not payloads:
            raise AssertionError(f"Unexpected URL requested: {url}")
        payload = payloads.pop(0)
        return FakeResponse(payload)


class ApiClientTests(unittest.TestCase):
    """Regression tests for warning XML fetching."""

    def test_retry_uses_exponential_backoff(self) -> None:
        forecast_url = API.FORECAST_URL.format(office_code=OFFICE_CODE)
        session = FakeSession(
            {
                forecast_url: [
                    AIOHTTP.ClientConnectionError("first failure"),
                    AIOHTTP.ClientConnectionError("second failure"),
                    AIOHTTP.ClientConnectionError("third failure"),
                    [{"publishingOffice": "気象庁", "timeSeries": []}],
                ]
            }
        )
        client = API.HaWeatherJmaApiClient(
            session,
            retries=3,
            retry_backoff_base_seconds=1,
        )
        sleep_calls: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        with patch.object(API.asyncio, "sleep", new=fake_sleep):
            payload = asyncio.run(client.fetch_forecast(OFFICE_CODE))

        self.assertEqual(payload, [{"publishingOffice": "気象庁", "timeSeries": []}])
        self.assertEqual(sleep_calls, [1, 2, 4])

    def test_forecast_fetch_retries_on_transient_not_found(self) -> None:
        forecast_url = API.FORECAST_URL.format(office_code=OFFICE_CODE)
        session = FakeSession(
            {
                forecast_url: [
                    AIOHTTP.ClientResponseError(status=404),
                    [{"publishingOffice": "気象庁", "timeSeries": []}],
                ]
            }
        )
        client = API.HaWeatherJmaApiClient(session)

        payload = asyncio.run(client.fetch_forecast(OFFICE_CODE))

        self.assertEqual(payload, [{"publishingOffice": "気象庁", "timeSeries": []}])

    def test_stale_cached_warning_urls_are_refreshed_and_retried(self) -> None:
        session = FakeSession(
            {
                SHORT_FEED_URL: [build_feed(), build_feed()],
                LONG_FEED_URL: [build_feed(FRESH_URL_53, FRESH_URL_55)],
                STALE_URL_53: [AIOHTTP.ClientResponseError(status=404)],
                STALE_URL_55: [AIOHTTP.ClientResponseError(status=404)],
                FRESH_URL_53: ["<Report>fresh53</Report>"],
                FRESH_URL_55: ["<Report>fresh55</Report>"],
            }
        )
        client = API.HaWeatherJmaApiClient(session)
        client._warning_xml_urls[OFFICE_CODE] = {
            "VPWW53": STALE_URL_53,
            "VPWW55": STALE_URL_55,
        }

        documents = asyncio.run(client.fetch_warning_xml_documents(OFFICE_CODE))

        self.assertEqual(
            documents, ["<Report>fresh53</Report>", "<Report>fresh55</Report>"]
        )
        self.assertEqual(
            client._warning_xml_urls[OFFICE_CODE],
            {
                "VPWW53": FRESH_URL_53,
                "VPWW55": FRESH_URL_55,
            },
        )

    def test_partial_warning_fetch_failure_keeps_successful_documents(self) -> None:
        session = FakeSession(
            {
                SHORT_FEED_URL: [
                    build_feed(FRESH_URL_53, FRESH_URL_55),
                    build_feed(FRESH_URL_53, FRESH_URL_55),
                ],
                LONG_FEED_URL: [build_feed(FRESH_URL_53, FRESH_URL_55)],
                FRESH_URL_53: [
                    "<Report>ok53</Report>",
                    AIOHTTP.ClientConnectionError("retry still fails"),
                ],
                FRESH_URL_55: [
                    AIOHTTP.ClientConnectionError("first fetch fails"),
                    AIOHTTP.ClientConnectionError("retry still fails"),
                ],
            }
        )
        client = API.HaWeatherJmaApiClient(session)

        documents = asyncio.run(client.fetch_warning_xml_documents(OFFICE_CODE))

        self.assertEqual(documents, ["<Report>ok53</Report>"])
        self.assertEqual(
            client._warning_xml_urls[OFFICE_CODE], {"VPWW53": FRESH_URL_53}
        )


if __name__ == "__main__":
    unittest.main()
