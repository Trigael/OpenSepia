"""
AI Dev Team — Plane.so API Client

Shared HTTP client for all Plane.so interactions.
Provides rate limiting, caching, and cursor-based pagination.
"""

import json
import logging
import os
import time
import urllib.request
import urllib.parse
import urllib.error
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional, Union

from opensepia.config import PLANE_API_TIMEOUT

logger = logging.getLogger(__name__)

# Rate limit: 60 requests per minute
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 58  # leave 2 request margin
PAGINATION_MAX = 100


@dataclass
class PlaneConfig:
    """Configuration for Plane.so API access."""
    api_key: str = ""
    workspace_slug: str = ""
    project_id: str = ""
    base_url: str = "http://localhost:3000"

    @classmethod
    def from_env(cls) -> "PlaneConfig":
        return cls(
            api_key=os.environ.get("PLANE_API_KEY", "").strip(),
            workspace_slug=os.environ.get("PLANE_WORKSPACE_SLUG", "").strip(),
            project_id=os.environ.get("PLANE_PROJECT_ID", "").strip(),
            base_url=os.environ.get("PLANE_BASE_URL", "http://localhost:3000").strip().rstrip("/"),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.workspace_slug)

    @property
    def api_base(self) -> str:
        """Base URL for project-scoped API calls."""
        return (
            f"{self.base_url}/api/v1/workspaces/{self.workspace_slug}"
            f"/projects/{self.project_id}"
        )

    @property
    def workspace_base(self) -> str:
        """Base URL for workspace-scoped API calls."""
        return f"{self.base_url}/api/v1/workspaces/{self.workspace_slug}"

    @property
    def global_base(self) -> str:
        """Base URL for global API calls (e.g., workspace creation)."""
        return f"{self.base_url}/api/v1"


class PlaneCache:
    """In-memory TTL cache for Plane.so API responses.

    Different TTLs for different entity types:
    - Stable entities (states, labels, members): 300s
    - Work items and pages: 60s
    """

    TTL_STABLE = 300  # states, labels, members, cycles
    TTL_VOLATILE = 60  # work items, pages

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.time() - ts > self._ttl_for(key):
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (time.time(), value)

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def invalidate_prefix(self, prefix: str) -> None:
        keys = [k for k in self._store if k.startswith(prefix)]
        for k in keys:
            del self._store[k]

    def clear(self) -> None:
        self._store.clear()

    def _ttl_for(self, key: str) -> int:
        if key.startswith(("states", "labels", "members", "cycles")):
            return self.TTL_STABLE
        return self.TTL_VOLATILE


class RateLimiter:
    """Sliding window rate limiter for Plane.so API (60 req/min)."""

    def __init__(self, max_requests: int = RATE_LIMIT_MAX, window: int = RATE_LIMIT_WINDOW):
        self.max_requests = max_requests
        self.window = window
        self._timestamps: deque[float] = deque()

    def wait_if_needed(self) -> None:
        now = time.time()
        # Purge timestamps outside the window
        while self._timestamps and self._timestamps[0] < now - self.window:
            self._timestamps.popleft()

        if len(self._timestamps) >= self.max_requests:
            oldest = self._timestamps[0]
            wait_time = self.window - (now - oldest) + 0.1
            if wait_time > 0:
                logger.warning("Plane rate limit: sleeping %.1fs", wait_time)
                time.sleep(wait_time)

        self._timestamps.append(time.time())


class PlaneClient:
    """HTTP client for Plane.so API with caching and rate limiting."""

    def __init__(self, config: Optional[PlaneConfig] = None):
        self.config = config or PlaneConfig.from_env()
        self.cache = PlaneCache()
        self._rate_limiter = RateLimiter()

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-API-Key": self.config.api_key,
        }

    def api(
        self,
        method: str,
        endpoint: str,
        data: Optional[dict] = None,
        params: Optional[dict] = None,
        workspace_scope: bool = False,
        global_scope: bool = False,
    ) -> Union[dict, list]:
        """Make a Plane.so API request.

        Args:
            method: HTTP method (GET, POST, PATCH, DELETE)
            endpoint: API path (appended to project or workspace base)
            data: JSON body for POST/PATCH
            params: Query parameters
            workspace_scope: If True, use workspace base URL instead of project
            global_scope: If True, use global base URL (for workspace creation)
        """
        if global_scope:
            base = self.config.global_base
        elif workspace_scope:
            base = self.config.workspace_base
        else:
            base = self.config.api_base
        url = f"{base}{endpoint}"
        if params:
            url += "?" + urllib.parse.urlencode(params)

        self._rate_limiter.wait_if_needed()

        body = json.dumps(data).encode("utf-8") if data else None
        req = urllib.request.Request(url, data=body, method=method, headers=self.headers)

        try:
            with urllib.request.urlopen(req, timeout=PLANE_API_TIMEOUT) as resp:
                response_body = resp.read().decode("utf-8")
                if response_body:
                    return json.loads(response_body)
                return {"status": "ok"}
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            message = error_body
            try:
                error_data = json.loads(error_body)
                if isinstance(error_data, dict):
                    message = error_data.get("error", error_data.get("detail", error_body))
            except (json.JSONDecodeError, ValueError):
                pass
            logger.error("Plane API %s %s: %d — %s", method, endpoint, e.code, message)
            return {"error": e.code, "message": str(message)}
        except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError) as e:
            logger.error("Plane API %s %s: %s", method, endpoint, e)
            return {"error": str(e)}

    def api_with_retry(
        self,
        method: str,
        endpoint: str,
        data: Optional[dict] = None,
        params: Optional[dict] = None,
        workspace_scope: bool = False,
        max_retries: int = 3,
    ) -> Union[dict, list]:
        """API request with retry on rate limit (429)."""
        for attempt in range(max_retries + 1):
            result = self.api(method, endpoint, data=data, params=params,
                              workspace_scope=workspace_scope)
            if isinstance(result, dict) and result.get("error") == 429:
                if attempt < max_retries:
                    wait = 2 ** attempt
                    logger.warning("Plane 429 on %s %s — retry %d/%d in %ds",
                                   method, endpoint, attempt + 1, max_retries, wait)
                    time.sleep(wait)
                    continue
            return result
        return {"error": "max retries exhausted"}

    def paginate(
        self,
        endpoint: str,
        params: Optional[dict] = None,
        workspace_scope: bool = False,
    ) -> list[dict]:
        """Fetch all pages of a paginated endpoint."""
        all_results: list[dict] = []
        page_params = dict(params or {})
        page_params["per_page"] = PAGINATION_MAX

        while True:
            result = self.api("GET", endpoint, params=page_params,
                              workspace_scope=workspace_scope)

            if isinstance(result, list):
                all_results.extend(result)
                break

            if isinstance(result, dict):
                if "error" in result:
                    logger.warning("Plane pagination error on %s: %s", endpoint, result)
                    break

                # Plane API wraps paginated results in a "results" key
                results = result.get("results", [])
                if isinstance(results, list):
                    all_results.extend(results)

                next_cursor = result.get("next_cursor")
                if not next_cursor or not results:
                    break
                page_params["cursor"] = next_cursor

        return all_results

    def get_cached(
        self,
        cache_key: str,
        endpoint: str,
        params: Optional[dict] = None,
        workspace_scope: bool = False,
        paginate: bool = False,
    ) -> Any:
        """GET with cache. Returns cached value if available, else fetches."""
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        if paginate:
            result = self.paginate(endpoint, params=params,
                                   workspace_scope=workspace_scope)
        else:
            result = self.api("GET", endpoint, params=params,
                              workspace_scope=workspace_scope)

        if not (isinstance(result, dict) and "error" in result):
            self.cache.set(cache_key, result)

        return result
