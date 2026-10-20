import pytest

from term_wyrm.apis import MissingApiKey, UMLSSearchAPI, available_apis, get_api

UMLS = "https://uts-ws.nlm.nih.gov/rest/search/current"


@pytest.fixture
def http(fake_http):
    return fake_http({UMLS: "umls_search_seizure"})


def test_missing_key(http, monkeypatch):
    monkeypatch.delenv("UMLS_API_KEY", raising=False)
    with pytest.raises(MissingApiKey):
        UMLSSearchAPI(http=http).search("seizure")
    assert http.calls == []


def test_key_from_environment(http, monkeypatch):
    monkeypatch.setenv("UMLS_API_KEY", "ENVKEY")
    UMLSSearchAPI(http=http).search("seizure")
    assert http.params["apiKey"] == "ENVKEY"


def test_request(http):
    page = UMLSSearchAPI(http=http, api_key="SECRET").search(
        "HP:0001250", ["HP", "snomedct", "mesh"]
    )
    assert http.params == {
        "string": "HPO:0001250",
        "returnIdType": "code",
        "apiKey": "SECRET",
        "sabs": "HPO,SNOMEDCT_US,MSH",
        "pageNumber": 1,
        "pageSize": 25,
    }
    assert "SECRET" not in page.url


def test_omim_filter_falls_back_to_preferred_prefix(http):
    # omim's UMLS prefix is "" (bare codes), which can't be a filter name.
    UMLSSearchAPI(http=http, api_key="k").search("OMIM:163950", ["omim"])
    assert http.params["string"] == "163950"
    assert http.params["sabs"] == "omim"


def test_results_use_preferred_prefixes(http):
    page = UMLSSearchAPI(http=http, api_key="k").search("seizure")
    assert [c.code for c in page][:4] == [
        "snomedct:128613002",
        "mesh:D004827",
        "HP:0001250",  # UMLS's HPO codes already carry "HP:"; not doubled
        "snomedct:91175000",
    ]
    assert {c.prefix for c in page} == {"snomedct", "mesh", "HP"}
    assert page.concepts[0].system == "http://snomed.info/sct"
    assert page.skipped == 0


def test_paging_uses_one_based_page_numbers(http):
    api = UMLSSearchAPI(http=http, api_key="k")
    page = api.search("seizure", page_size=25)
    assert (http.params["pageNumber"], http.params["pageSize"]) == (1, 25)
    assert page.total == 636 and page.more_available

    api.search("seizure", page_size=25, offset=50)
    assert http.params["pageNumber"] == 3


def test_page_size_limit(http):
    api = UMLSSearchAPI(http=http, api_key="k")
    api.search("seizure", page_size=500)
    assert http.params["pageSize"] == 500
    with pytest.raises(ValueError):
        api.search("seizure", page_size=501)


def test_no_results(fake_http):
    http = fake_http({UMLS: "umls_search_none"})
    page = UMLSSearchAPI(http=http, api_key="k").search("zzz")
    assert len(page) == 0 and page.skipped == 0
    assert page.total == 0 and not page.more_available


def test_documented_none_placeholder_is_dropped(fake_http):
    payload = {"result": {"results": [{"ui": "NONE", "name": "NO RESULTS"}]}}
    page = UMLSSearchAPI(http=fake_http({UMLS: payload}), api_key="k").search("zzz")
    assert len(page) == 0 and page.skipped == 0


def test_registry():
    assert set(available_apis()) == {"ols", "ols2", "olsd", "umls"}
    assert isinstance(get_api("UMLS", api_key="k"), UMLSSearchAPI)
    with pytest.raises(KeyError, match="available"):
        get_api("bioportal")
