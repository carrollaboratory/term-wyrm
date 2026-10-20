"""Minimal JSON-over-HTTP client built on the standard library."""

import json
import logging
import re
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any, Protocol
from urllib.parse import quote, urlencode

logger = logging.getLogger(__name__)

Params = Mapping[str, str | int | bool]

_SECRET_PARAM = re.compile(r"((?:api)?key=)[^&]+", re.IGNORECASE)


def redact_url(url: str) -> str:
    """Replace the value of any ``key=``/``apiKey=`` query parameter."""
    return _SECRET_PARAM.sub(r"\1{api_key}", url)


def build_url(url: str, params: Params | None = None) -> str:
    if not params:
        return url
    encoded = {
        k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()
    }
    sep = "&" if "?" in url else "?"
    return url + sep + urlencode(encoded, quote_via=quote, safe=",")


class ApiError(RuntimeError):
    """A request failed or returned something other than JSON."""

    def __init__(self, message: str, url: str, status: int | None = None):
        super().__init__(f"{message} ({redact_url(url)})")
        self.url = redact_url(url)
        self.status = status


class JsonClient(Protocol):
    """What adapters need from an HTTP client; tests substitute a fake."""

    def get_json(self, url: str, params: Params | None = None) -> Any: ...


class HttpClient:
    """GETs JSON with a timeout and a few retries on transient failures."""

    RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

    def __init__(
        self, timeout: float = 30.0, retries: int = 2, backoff: float = 1.0
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff

    def get_json(self, url: str, params: Params | None = None) -> Any:
        full_url = build_url(url, params)
        request = urllib.request.Request(
            full_url, headers={"Accept": "application/json"}
        )
        for attempt in range(self.retries + 1):
            logger.debug("GET %s", redact_url(full_url))
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.load(response)
            except urllib.error.HTTPError as e:
                if e.code not in self.RETRY_STATUSES or attempt == self.retries:
                    raise ApiError(f"HTTP {e.code}", full_url, e.code) from e
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt == self.retries:
                    raise ApiError(f"Request failed: {e}", full_url) from e
            except json.JSONDecodeError as e:
                raise ApiError("Response was not JSON", full_url) from e
            time.sleep(self.backoff * 2**attempt)
        raise AssertionError("unreachable")
