import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


class FakeHttp:
    """Serves responses by URL (without query string) and records each call.

    A route maps to a fixture name, a payload dict, or a list of either that
    is served one per call (for paging).
    """

    def __init__(self, routes: dict[str, str | dict | list]):
        self.routes = {
            url: iter(r) if isinstance(r, list) else r for url, r in routes.items()
        }
        self.calls: list[tuple[str, dict]] = []

    def get_json(self, url, params=None):
        self.calls.append((url, dict(params or {})))
        try:
            payload = self.routes[url]
        except KeyError:
            raise AssertionError(f"Unexpected request to {url}") from None
        if not isinstance(payload, (str, dict)):
            payload = next(payload)
        return load_fixture(payload) if isinstance(payload, str) else payload

    def calls_to(self, suffix: str) -> list[dict]:
        return [params for url, params in self.calls if url.endswith(suffix)]

    @property
    def params(self) -> dict:
        """Parameters of the most recent call."""
        return self.calls[-1][1]


@pytest.fixture
def fake_http():
    return FakeHttp
