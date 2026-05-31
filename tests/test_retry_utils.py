"""
Unit tests for retry_utils (stdlib unittest only).

Run via: python3 -m unittest discover tests
"""

import unittest

from retry_utils import is_transient_api_error


class TestIsTransientApiError(unittest.TestCase):
    """Test is_transient_api_error returns True/False sensibly for example exceptions."""

    def test_transient_rate_limit_variants(self):
        self.assertTrue(is_transient_api_error(Exception("429 Too Many Requests")))
        self.assertTrue(is_transient_api_error(Exception("rate_limit exceeded")))
        self.assertTrue(is_transient_api_error(Exception("Rate limit hit")))
        self.assertTrue(is_transient_api_error(Exception("HTTP 429")))

    def test_transient_server_errors(self):
        for code in ("500", "502", "503", "504"):
            self.assertTrue(is_transient_api_error(Exception(f"Server returned {code}")))
        self.assertTrue(is_transient_api_error(Exception("server_error: overloaded")))
        self.assertTrue(is_transient_api_error(Exception("503 Service Unavailable")))
        self.assertTrue(is_transient_api_error(Exception("internal error occurred")))

    def test_transient_network_timeouts(self):
        self.assertTrue(is_transient_api_error(Exception("Connection timed out")))
        self.assertTrue(is_transient_api_error(Exception("Request timeout after 30s")))
        self.assertTrue(is_transient_api_error(Exception("Connection refused")))
        self.assertTrue(is_transient_api_error(Exception("Service unavailable due to high demand")))
        self.assertTrue(is_transient_api_error(Exception("resource_exhausted")))

    def test_non_transient_client_errors(self):
        self.assertFalse(is_transient_api_error(Exception("401 Unauthorized")))
        self.assertFalse(is_transient_api_error(Exception("404 Not Found")))
        self.assertFalse(is_transient_api_error(Exception("400 Bad Request")))
        self.assertFalse(is_transient_api_error(ValueError("invalid input")))
        self.assertFalse(is_transient_api_error(Exception("permission denied")))
        self.assertFalse(is_transient_api_error(Exception("authentication failed")))

    def test_edge_cases(self):
        # Empty / weird exceptions still return bool, never crash
        self.assertFalse(is_transient_api_error(Exception("")))
        self.assertFalse(is_transient_api_error(Exception("completely unrelated error")))
        self.assertIsInstance(is_transient_api_error(Exception("foo 429 bar")), bool)


if __name__ == "__main__":
    unittest.main()
