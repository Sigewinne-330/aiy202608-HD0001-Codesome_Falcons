import asyncio
import logging
import sys
import unittest
from pathlib import Path

import httpx
from cryptography.fernet import Fernet

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.managebac_security import (  # noqa: E402
    IBUDDY_CALENDAR_CLIENT,
    MANAGEBAC_ICAL_USER_AGENT,
    ManageBacFetchError,
    ManageBacURLValidationError,
    assert_public_remote_host,
    decrypt_feed_url,
    encrypt_feed_url,
    fetch_calendar,
    normalize_feed_url,
)


class ManageBacSecurityTests(unittest.TestCase):
    def test_http_client_info_logging_is_disabled_for_credential_urls(self):
        self.assertGreaterEqual(
            logging.getLogger("httpx").getEffectiveLevel(),
            logging.WARNING,
        )

    def test_webcal_normalization_and_allowed_host(self):
        value = normalize_feed_url(
            "webcal://hanacademy.managebac.com/student/events/token/private.ics"
        )
        self.assertEqual("hanacademy.managebac.com", value.host)
        self.assertEqual(
            "https://hanacademy.managebac.com/student/events/token/private.ics",
            value.url,
        )

    def test_rejects_unsafe_url_shapes(self):
        rejected = [
            "http://school.managebac.com/calendar.ics",
            "https://user:pass@school.managebac.com/calendar.ics",
            "https://school.managebac.com:8443/calendar.ics",
            "https://example.com/calendar.ics",
            "https://school.managebac.com/",
        ]
        for value in rejected:
            with self.subTest(value=value):
                with self.assertRaises(ManageBacURLValidationError):
                    normalize_feed_url(value)

    def test_rejects_private_dns_answers(self):
        with self.assertRaises(ManageBacURLValidationError) as context:
            assert_public_remote_host(
                "school.managebac.com",
                resolve_addresses=lambda _host: ["127.0.0.1"],
            )
        self.assertEqual("unsafe_target", context.exception.code)
        assert_public_remote_host(
            "school.managebac.com",
            resolve_addresses=lambda _host: ["8.8.8.8"],
        )

    def test_credential_round_trip_and_wrong_key(self):
        key = Fernet.generate_key().decode("ascii")
        other_key = Fernet.generate_key().decode("ascii")
        raw = "https://school.managebac.com/student/events/token/private.ics"
        encrypted = encrypt_feed_url(raw, key=key)
        self.assertNotIn("private", encrypted)
        self.assertEqual(raw, decrypt_feed_url(encrypted, key=key))
        with self.assertRaises(Exception):
            decrypt_feed_url(encrypted, key=other_key)

    def test_fetch_uses_conditional_headers_and_bounds_redirects(self):
        calls = []

        def handler(request: httpx.Request):
            calls.append(request)
            if request.url.path == "/first.ics":
                return httpx.Response(302, headers={"Location": "/calendar.ics"})
            return httpx.Response(
                200,
                headers={"ETag": '"v2"', "Last-Modified": "Tue, 18 Aug 2026 08:00:00 GMT"},
                content=b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n",
            )

        result = asyncio.run(
            fetch_calendar(
                "webcal://school.managebac.com/first.ics",
                etag='"v1"',
                transport=httpx.MockTransport(handler),
                resolve_addresses=lambda _host: ["8.8.8.8"],
            )
        )
        self.assertEqual(200, result.http_status)
        self.assertEqual('"v2"', result.etag)
        self.assertEqual(2, len(calls))
        self.assertEqual('"v1"', calls[0].headers["if-none-match"])
        self.assertTrue(all(call.headers["user-agent"] == MANAGEBAC_ICAL_USER_AGENT for call in calls))
        self.assertTrue(all(call.headers["x-ibuddy-client"] == IBUDDY_CALENDAR_CLIENT for call in calls))

    def test_fetch_logs_safe_403_diagnostics_without_exposing_token(self):
        transport = httpx.MockTransport(
            lambda _request: httpx.Response(
                403,
                headers={
                    "Server": "cloudflare",
                    "Content-Type": "text/html; charset=UTF-8",
                    "CF-Ray": "test-ray-HKG",
                },
                content=b"response body must not be logged",
            )
        )
        with self.assertLogs("services.managebac_security", level="WARNING") as captured:
            with self.assertRaises(ManageBacFetchError):
                asyncio.run(
                    fetch_calendar(
                        "https://school.managebac.com/student/events/token/private-test-token.ics",
                        transport=transport,
                        resolve_addresses=lambda _host: ["8.8.8.8"],
                    )
                )

        output = "\n".join(captured.output)
        self.assertIn("status=403", output)
        self.assertIn("host=school.managebac.com", output)
        self.assertIn("server=cloudflare", output)
        self.assertIn("cf_ray=test-ray-HKG", output)
        self.assertNotIn("private-test-token", output)
        self.assertNotIn("response body", output)

    def test_fetch_rejects_oversized_streamed_body(self):
        from config import settings

        original_limit = settings.MANAGEBAC_MAX_FEED_BYTES
        settings.MANAGEBAC_MAX_FEED_BYTES = 65536
        try:
            transport = httpx.MockTransport(
                lambda _request: httpx.Response(200, content=b"x" * 65537)
            )
            with self.assertRaises(Exception) as context:
                asyncio.run(
                    fetch_calendar(
                        "https://school.managebac.com/large.ics",
                        transport=transport,
                        resolve_addresses=lambda _host: ["8.8.8.8"],
                    )
                )
            self.assertEqual("feed_too_large", context.exception.code)
        finally:
            settings.MANAGEBAC_MAX_FEED_BYTES = original_limit

    def test_fetch_preserves_numeric_retry_after_without_exposing_the_url(self):
        transport = httpx.MockTransport(
            lambda _request: httpx.Response(429, headers={"Retry-After": "120"})
        )
        with self.assertRaises(ManageBacFetchError) as context:
            asyncio.run(
                fetch_calendar(
                    "https://school.managebac.com/student/events/token/test-only.ics",
                    transport=transport,
                    resolve_addresses=lambda _host: ["8.8.8.8"],
                )
            )
        self.assertEqual(429, context.exception.http_status)
        self.assertEqual(120, context.exception.retry_after_seconds)
        self.assertNotIn("test-only", str(context.exception))


if __name__ == "__main__":
    unittest.main()
