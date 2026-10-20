from urllib.parse import quote

import pytest

from term_wyrm import SearchService
from term_wyrm.apis import ApiError, OLSHierarchyAPI, UMLSSearchAPI
from term_wyrm.vocabulary import Curie

OLS = "https://www.ebi.ac.uk/ols4/api"
OLS2 = f"{OLS}/v2/entities"
UMLS = "https://uts-ws.nlm.nih.gov/rest/search/current"
HP_0002197 = "http://purl.obolibrary.org/obo/HP_0002197"
TERMS = f"{OLS}/ontologies/hp/terms/{quote(quote(HP_0002197, safe=''), safe='')}"


def ols_doc(obo_id, ontology_prefix="HP"):
    prefix, local = obo_id.split(":")
    return {
        "obo_id": obo_id,
        "ontology_prefix": ontology_prefix,
        "iri": f"http://purl.obolibrary.org/obo/{prefix}_{local}",
        "label": obo_id,
    }


def ols_page(*docs, total=100):
    return {"response": {"numFound": total, "docs": list(docs)}}


class FailingHttp:
    def __init__(self, http, failing_url):
        self.http, self.failing_url = http, failing_url

    def get_json(self, url, params=None):
        if url == self.failing_url:
            raise ApiError("HTTP 503", f"{url}?apiKey=SECRET", 503)
        return self.http.get_json(url, params)


class TestConstruction:
    def test_apis_share_vocabularies_and_http(self, fake_http):
        http = fake_http({})
        service = SearchService(["ols", "ols2"], http=http)
        assert [a.api_id for a in service.apis] == ["ols", "ols2"]
        assert all(a.http is http for a in service.apis)
        assert all(a.vocabularies is service.vocabularies for a in service.apis)

    def test_accepts_instances(self, fake_http):
        umls = UMLSSearchAPI(api_key="k", http=fake_http({}))
        assert SearchService(["ols", umls]).apis[1] is umls

    def test_rejects_hierarchy_and_duplicates(self):
        with pytest.raises(TypeError):
            SearchService(["olsd"])
        with pytest.raises(ValueError):
            SearchService(["ols", "ols"])

    def test_hierarchy_reuses_ols2(self, fake_http):
        service = SearchService(["ols2"], http=fake_http({}))
        assert isinstance(service.hierarchy, OLSHierarchyAPI)
        assert service.hierarchy.entities is service.apis[0]


class TestSearch:
    @pytest.fixture
    def http(self, fake_http):
        return fake_http(
            {OLS2: "ols2_search_seizure_page1", UMLS: "umls_search_seizure"}
        )

    @pytest.fixture
    def service(self, http):
        return SearchService(["ols2", UMLSSearchAPI(api_key="k", http=http)], http=http)

    def test_each_api_gets_its_own_names(self, service, http):
        service.search("HP:0001250", ["HP", "MONDO"])
        assert http.calls_to("/v2/entities")[0]["ontologyId"] == "hp,mondo"
        assert http.calls_to("/search/current")[0]["string"] == "HPO:0001250"
        assert http.calls_to("/search/current")[0]["sabs"] == "HPO,MONDO"

    def test_merges_in_api_order_without_duplicates(self, service):
        result = service.search("seizure", ["HP"])
        assert list(result.pages) == ["ols2", "umls"]
        codes = [c.code for c in result]
        assert codes[:5] == [
            "HP:0002349",
            "HP:0020220",
            "HP:0011169",
            "MONDO:0043264",
            "HP:0033349",
        ]
        # HP:0002349 is in both; the OLS copy (with its purl IRI) is kept.
        assert codes.count("HP:0002349") == 1
        kept = next(c for c in result if c.code == "HP:0002349")
        assert kept.source == "ols2"
        assert kept.iri == "http://purl.obolibrary.org/obo/HP_0002349"
        assert len(result) == 5 + 25 - 1

    def test_summary(self, service):
        result = service.search("seizure")
        assert result.more_available
        assert result.failures == []
        assert result.counts_by_prefix() == {
            "HP": 13,
            "MONDO": 1,
            "snomedct": 10,
            "mesh": 5,
        }
        assert sum(result.counts_by_prefix().values()) == len(result)

    def test_unknown_ontology_fails_before_any_request(self, service, http):
        with pytest.raises(KeyError):
            service.search("seizure", ["HP", "NOTAVOCAB"])
        assert http.calls == []

    def test_one_failing_api_does_not_sink_the_rest(self, http):
        failing = FailingHttp(http, UMLS)
        umls = UMLSSearchAPI(api_key="SECRET", http=failing)
        result = SearchService(["ols2", umls], http=failing).search("seizure")
        assert list(result.pages) == ["ols2"]
        assert len(result) == 5
        [failure] = result.failures
        assert failure.source == "umls"
        assert "503" in failure.error
        assert "SECRET" not in failure.error and "SECRET" not in failure.url

    def test_missing_umls_key_is_a_failure(self, http, monkeypatch):
        monkeypatch.delenv("UMLS_API_KEY", raising=False)
        result = SearchService(["ols2", "umls"], http=http).search("seizure")
        assert [f.source for f in result.failures] == ["umls"]
        assert "UMLS_API_KEY" in result.failures[0].error

    def test_search_many(self, service):
        results = service.search_many(["seizure", "HP:0001250"], ["HP"])
        assert list(results) == ["seizure", "HP:0001250"]
        assert results["HP:0001250"].query == "HP:0001250"


class TestFirstMatch:
    def test_skips_other_vocabularies(self, fake_http):
        http = fake_http({f"{OLS}/search": "ols_search_brain_hp"})
        match = SearchService(["ols"], http=http).first_match("brain", "hp")
        # The first result is an imported UBERON term.
        assert match.code == "HP:0002283"

    def test_pages_until_found(self, fake_http):
        http = fake_http(
            {
                f"{OLS}/search": [
                    ols_page(ols_doc("UBERON:0000955"), ols_doc("UBERON:0000956")),
                    ols_page(ols_doc("UBERON:0000957"), ols_doc("HP:0002283")),
                ]
            }
        )
        service = SearchService(["ols"], http=http)
        match = service.first_match("brain", "HPO", page_size=2)
        assert match.curie == Curie("HP", "0002283")
        assert [p["start"] for p in http.calls_to("/search")] == [0, 2]

    def test_none_when_exhausted(self, fake_http):
        http = fake_http({f"{OLS}/search": ols_page(ols_doc("UBERON:1"), total=1)})
        assert SearchService(["ols"], http=http).first_match("brain", "HP") is None
        assert len(http.calls) == 1

    def test_respects_max_pages(self, fake_http):
        http = fake_http({f"{OLS}/search": ols_page(ols_doc("UBERON:1"))})
        service = SearchService(["ols"], http=http)
        assert service.first_match("brain", "HP", page_size=1, max_pages=3) is None
        assert len(http.calls) == 3

    def test_falls_through_to_next_api(self, fake_http):
        http = fake_http(
            {
                f"{OLS}/search": ols_page(ols_doc("UBERON:1"), total=1),
                UMLS: "umls_search_seizure",
            }
        )
        umls = UMLSSearchAPI(api_key="k", http=http)
        match = SearchService(["ols", umls], http=http).first_match("seizure", "HP")
        assert (match.code, match.source) == ("HP:0001250", "umls")

    def test_raises_when_an_api_failed_and_nothing_matched(self, fake_http):
        http = FailingHttp(fake_http({}), f"{OLS}/search")
        with pytest.raises(ApiError):
            SearchService(["ols"], http=http).first_match("brain", "HP")


class TestDescendants:
    def test_free_text_uses_first_ols2_match(self, fake_http):
        http = fake_http(
            {
                OLS2: ["ols2_lookup_HP_0002197", "ols2_lookup_HP_0002197"],
                f"{TERMS}/descendants": "olsd_descendants_HP_0002197",
            }
        )
        tree = SearchService(["ols2"], http=http).descendants(
            "generalized-onset seizure", "HP"
        )
        search, lookup = http.calls_to("/v2/entities")
        assert search["search"] == "generalized-onset seizure"
        assert search["ontologyId"] == "hp"
        assert lookup["iri"] == HP_0002197
        assert tree.parent.code == "HP:0002197"
        assert len(tree) > 0

    def test_curie_goes_straight_to_lookup(self, fake_http):
        http = fake_http(
            {
                OLS2: "ols2_lookup_HP_0002197",
                f"{TERMS}/children": "olsd_children_HP_0002197",
            }
        )
        tree = SearchService(["ols"], http=http).children("HPO:0002197")
        assert tree.direct
        assert tree.parent.code == "HP:0002197"
        [lookup] = http.calls_to("/v2/entities")
        assert lookup["exactMatch"] is True

    def test_free_text_needs_an_ontology(self, fake_http):
        with pytest.raises(ValueError):
            SearchService(["ols2"], http=fake_http({})).descendants("seizure")

    def test_no_match(self, fake_http):
        http = fake_http({OLS2: {"elements": [], "totalElements": 0}})
        with pytest.raises(LookupError):
            SearchService(["ols2"], http=http).descendants("nothing", "HP")
