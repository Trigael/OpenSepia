"""Tests for integrations/providers/http_mixin.py — HTTP helpers."""

import json
import urllib.error
from unittest.mock import patch, MagicMock

import pytest

from opensepia.integrations.providers.http_mixin import HTTPMixin, build_url


# =============================================================================
# build_url
# =============================================================================

class TestBuildUrl:
    def test_simple(self):
        assert build_url("https://api.example.com", "/repos") == "https://api.example.com/repos"

    def test_with_params(self):
        url = build_url("https://api.example.com", "/repos", {"page": "1", "per_page": "10"})
        assert "page=1" in url
        assert "per_page=10" in url

    def test_no_params(self):
        url = build_url("https://api.example.com", "/repos", None)
        assert "?" not in url


# =============================================================================
# _http_request
# =============================================================================

class TestHttpRequest:
    @patch("opensepia.integrations.providers.http_mixin.urllib.request.urlopen")
    def test_get_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"id": 1}).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = HTTPMixin._http_request("https://api.example.com/test")
        assert result == {"id": 1}

    @patch("opensepia.integrations.providers.http_mixin.urllib.request.urlopen")
    def test_post_with_data(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"status": "created"}).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = HTTPMixin._http_request(
            "https://api.example.com/test",
            method="POST",
            data={"name": "test"},
        )
        assert result == {"status": "created"}

    @patch("opensepia.integrations.providers.http_mixin.urllib.request.urlopen")
    def test_empty_response(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b""
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = HTTPMixin._http_request("https://api.example.com/test")
        assert result == {"status": "ok"}

    @patch("opensepia.integrations.providers.http_mixin.urllib.request.urlopen")
    def test_http_error(self, mock_urlopen):
        error_body = json.dumps({"error": "not found"}).encode("utf-8")
        http_error = urllib.error.HTTPError(
            "https://api.example.com/test", 404, "Not Found",
            {}, MagicMock(read=MagicMock(return_value=error_body)),
        )
        http_error.read = MagicMock(return_value=error_body)
        mock_urlopen.side_effect = http_error

        result = HTTPMixin._http_request("https://api.example.com/test")
        assert result["error"] == 404
        assert result["message"] == "not found"

    @patch("opensepia.integrations.providers.http_mixin.urllib.request.urlopen")
    def test_http_error_plain_text(self, mock_urlopen):
        error_body = b"Server Error"
        http_error = urllib.error.HTTPError(
            "https://api.example.com/test", 500, "Internal Server Error",
            {}, MagicMock(read=MagicMock(return_value=error_body)),
        )
        http_error.read = MagicMock(return_value=error_body)
        mock_urlopen.side_effect = http_error

        result = HTTPMixin._http_request("https://api.example.com/test")
        assert result["error"] == 500

    @patch("opensepia.integrations.providers.http_mixin.urllib.request.urlopen")
    def test_url_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        result = HTTPMixin._http_request("https://api.example.com/test")
        assert "error" in result

    @patch("opensepia.integrations.providers.http_mixin.urllib.request.urlopen")
    def test_custom_headers(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok": true}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        HTTPMixin._http_request(
            "https://api.example.com/test",
            headers={"Authorization": "Bearer token123"},
        )
        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer token123"


# =============================================================================
# _http_request_with_retry
# =============================================================================

class TestHttpRequestWithRetry:
    @patch("opensepia.integrations.providers.http_mixin.urllib.request.urlopen")
    def test_success_no_retry(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"data": "ok"}).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = HTTPMixin._http_request_with_retry("https://api.example.com/test")
        assert result == {"data": "ok"}
        assert mock_urlopen.call_count == 1

    @patch("opensepia.integrations.providers.http_mixin.time.sleep")
    @patch("opensepia.integrations.providers.http_mixin.urllib.request.urlopen")
    def test_retries_on_429(self, mock_urlopen, mock_sleep):
        # First call: 429, second call: success
        error_429 = urllib.error.HTTPError(
            "url", 429, "Too Many Requests",
            {"Retry-After": "1"}, MagicMock(),
        )
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok": true}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        mock_urlopen.side_effect = [error_429, mock_resp]
        result = HTTPMixin._http_request_with_retry("https://api.example.com/test")
        assert result == {"ok": True}
        assert mock_sleep.call_count == 1

    @patch("opensepia.integrations.providers.http_mixin.time.sleep")
    @patch("opensepia.integrations.providers.http_mixin.urllib.request.urlopen")
    def test_max_retries_exhausted(self, mock_urlopen, mock_sleep):
        error_429 = urllib.error.HTTPError(
            "url", 429, "Too Many Requests",
            {"Retry-After": "0"}, MagicMock(),
        )
        mock_urlopen.side_effect = error_429

        result = HTTPMixin._http_request_with_retry(
            "https://api.example.com/test", max_retries=2,
        )
        # After 2 retries, should return error from the last 429
        assert "error" in result

    @patch("opensepia.integrations.providers.http_mixin.urllib.request.urlopen")
    def test_non_retryable_error(self, mock_urlopen):
        error_404 = urllib.error.HTTPError(
            "url", 404, "Not Found", {},
            MagicMock(read=MagicMock(return_value=b"not found")),
        )
        error_404.read = MagicMock(return_value=b"not found")
        mock_urlopen.side_effect = error_404

        result = HTTPMixin._http_request_with_retry("https://api.example.com/test")
        assert result["error"] == 404
        assert mock_urlopen.call_count == 1  # No retry for 404

    @patch("opensepia.integrations.providers.http_mixin.urllib.request.urlopen")
    def test_url_error_no_retry(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        result = HTTPMixin._http_request_with_retry("https://api.example.com/test")
        assert "error" in result
        assert mock_urlopen.call_count == 1

    @patch("opensepia.integrations.providers.http_mixin.urllib.request.urlopen")
    def test_empty_response(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b""
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = HTTPMixin._http_request_with_retry("https://api.example.com/test")
        assert result == {"status": "ok"}
