#!/usr/bin/env python3
"""
AI Dev Team — Shared HTTP Mixin

Common HTTP request/retry/error-handling logic for all provider classes.
Each provider supplies its own headers; this mixin handles the rest:
URL construction, JSON encoding/decoding, timeout, retry with exponential
backoff on rate-limit responses, and structured error returns.
"""

import json
import logging
import time
import urllib.request
import urllib.parse
import urllib.error
from typing import Optional, Union

logger = logging.getLogger(__name__)


class HTTPMixin:
    """Mixin providing shared HTTP helpers for board providers.

    Providers inherit this alongside BoardProvider and supply headers
    via their own config objects.  The mixin never touches auth headers
    — that stays in the provider.
    """

    # ---- low-level request ------------------------------------------------

    @staticmethod
    def _http_request(
        url: str,
        method: str = "GET",
        headers: Optional[dict] = None,
        data: Optional[dict] = None,
        timeout: int = 30,
    ) -> Union[dict, list]:
        """Make a single HTTP request with JSON encoding/decoding.

        Returns the decoded JSON body on success, or a dict with an
        ``"error"`` key on failure.
        """
        body = json.dumps(data).encode("utf-8") if data else None

        req = urllib.request.Request(
            url,
            data=body,
            method=method,
            headers=headers or {},
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                response_body = resp.read().decode("utf-8")
                if response_body:
                    return json.loads(response_body)
                return {"status": "ok"}
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            # Try to extract a structured message from the error body
            message = error_body
            try:
                error_data = json.loads(error_body)
                if isinstance(error_data, dict) and "error" in error_data:
                    message = error_data["error"]
            except (json.JSONDecodeError, ValueError):
                pass
            logger.error(
                "HTTP %s %s: %d — %s", method, url, e.code, error_body,
            )
            return {"error": e.code, "message": message}
        except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError) as e:
            logger.error("HTTP %s %s: %s", method, url, e)
            return {"error": str(e)}

    # ---- request with retry -----------------------------------------------

    @staticmethod
    def _http_request_with_retry(
        url: str,
        method: str = "GET",
        headers: Optional[dict] = None,
        data: Optional[dict] = None,
        timeout: int = 30,
        max_retries: int = 4,
        retry_on: tuple[int, ...] = (429,),
    ) -> Union[dict, list]:
        """HTTP request with exponential-backoff retry on rate-limit codes.

        Parameters
        ----------
        retry_on:
            HTTP status codes that should trigger a retry (e.g. 429, 403).
        """
        body = json.dumps(data).encode("utf-8") if data else None

        for attempt in range(max_retries + 1):
            req = urllib.request.Request(
                url,
                data=body,
                method=method,
                headers=headers or {},
            )

            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    response_body = resp.read().decode("utf-8")
                    if response_body:
                        return json.loads(response_body)
                    return {"status": "ok"}
            except urllib.error.HTTPError as e:
                if e.code in retry_on and attempt < max_retries:
                    retry_after = int(e.headers.get("Retry-After", 0))
                    wait = max(retry_after, 2 ** attempt)
                    logger.warning(
                        "HTTP %d on %s %s, retry %d/%d in %ds",
                        e.code, method, url, attempt + 1, max_retries, wait,
                    )
                    time.sleep(wait)
                    continue
                error_body = e.read().decode("utf-8", errors="replace")
                logger.error(
                    "HTTP %s %s: %d — %s", method, url, e.code, error_body,
                )
                return {"error": e.code, "message": error_body}
            except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError) as e:
                logger.error("HTTP %s %s: %s", method, url, e)
                return {"error": str(e)}

        return {"error": "max retries exhausted"}


def build_url(base: str, endpoint: str, params: Optional[dict] = None) -> str:
    """Construct a full URL from base + endpoint + optional query params."""
    url = f"{base}{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return url
