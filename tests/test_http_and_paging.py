import pytest

from term_wyrm.apis.http import build_url, redact_url
from term_wyrm.apis.paging import OffsetPaging, PagePaging


def test_build_url_encoding():
    url = build_url(
        "https://x/search", {"q": "brain cancer", "id": "HP:1", "o": "hp,mondo"}
    )
    assert url == "https://x/search?q=brain%20cancer&id=HP%3A1&o=hp,mondo"


def test_build_url_lowercases_booleans_and_appends():
    assert build_url("https://x?a=1", {"exact": True}) == "https://x?a=1&exact=true"
    assert build_url("https://x", {}) == "https://x"


@pytest.mark.parametrize(
    "url",
    [
        "https://x/search?string=a&apiKey=SECRET&b=1",
        "https://x/search?key=SECRET",
        "https://x/search?APIKEY=SECRET",
    ],
)
def test_redact_url(url):
    redacted = redact_url(url)
    assert "SECRET" not in redacted
    assert "{api_key}" in redacted


def test_offset_paging():
    assert OffsetPaging("start", "rows").params(50, 25) == {"start": 50, "rows": 25}


def test_page_paging():
    paging = PagePaging("pageNumber", "pageSize", first_page=1)
    assert paging.params(0, 25) == {"pageNumber": 1, "pageSize": 25}
    assert paging.params(50, 25) == {"pageNumber": 3, "pageSize": 25}
    with pytest.raises(ValueError, match="multiple"):
        paging.params(30, 25)
