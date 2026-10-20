from urllib.parse import quote

import pytest

from term_wyrm.apis import OLSEntitySearchAPI, OLSHierarchyAPI, OLSSearchAPI
from term_wyrm.vocabulary import Curie

OLS = "https://www.ebi.ac.uk/ols4/api"
HP_0002197 = "http://purl.obolibrary.org/obo/HP_0002197"
TERMS = f"{OLS}/ontologies/hp/terms/{quote(quote(HP_0002197, safe=''), safe='')}"


class TestSearch:
    @pytest.fixture
    def http(self, fake_http):
        return fake_http({f"{OLS}/search": "ols_search_brain_hp"})

    def test_request(self, http):
        page = OLSSearchAPI(http=http).search("brain", ["HPO"], page_size=40, offset=0)
        assert http.params == {"q": "brain", "ontology": "hp", "start": 0, "rows": 40}
        assert page.url == f"{OLS}/search?q=brain&ontology=hp&start=0&rows=40"
        assert page.source == "ols"

    def test_results_use_the_terms_own_prefix(self, http):
        page = OLSSearchAPI(http=http).search("brain", ["hp"], page_size=40)
        brain = page.concepts[0]
        # OLS reports ontology_prefix "HP" for this imported term.
        assert brain.code == "UBERON:0000955"
        assert brain.system == "http://purl.obolibrary.org/obo/uberon.owl"
        assert [c.prefix for c in page.concepts[1:]] == ["HP", "HP"]

    def test_counts(self, http):
        page = OLSSearchAPI(http=http).search("brain", ["hp"], page_size=40)
        assert page.total == 551
        assert page.more_available
        assert page.skipped == 0

    def test_description_is_a_tuple_of_strings(self, http):
        concept = OLSSearchAPI(http=http).search("brain").concepts[1]
        assert concept.description and all(
            isinstance(d, str) for d in concept.description
        )
        assert concept.to_dict()["description"] == list(concept.description)

    def test_curie_query_is_translated(self, fake_http):
        http = fake_http({f"{OLS}/search": "ols_search_epilepsy_snomed"})
        page = OLSSearchAPI(http=http).search("snomedct:84757009", ["SCT"])
        assert http.params["q"] == "SNOMED:84757009"
        assert http.params["ontology"] == "snomed"
        assert page.concepts[0].curie == Curie("snomedct", "84757009")
        assert {c.system for c in page} == {"http://snomed.info/sct"}

    def test_unknown_ontology_filter(self, http):
        with pytest.raises(KeyError, match="NOPE"):
            OLSSearchAPI(http=http).search("brain", ["NOPE"])
        assert http.calls == []

    def test_page_size_limits(self, http):
        api = OLSSearchAPI(http=http)
        with pytest.raises(ValueError):
            api.search("brain", page_size=501)
        with pytest.raises(ValueError):
            api.search("brain", offset=-1)


class TestEntitySearch:
    def test_page_offset_becomes_page_number(self, fake_http):
        http = fake_http({f"{OLS}/v2/entities": "ols2_search_seizure_page1"})
        page = OLSEntitySearchAPI(http=http).search(
            "seizure", ["HP", "Mondo"], page_size=5, offset=5
        )
        assert http.params == {
            "search": "seizure",
            "isDefiningOntology": True,
            "ontologyId": "hp,mondo",
            "page": 1,
            "size": 5,
        }
        assert [c.code for c in page] == [
            "HP:0002349",
            "HP:0020220",
            "HP:0011169",
            "MONDO:0043264",
            "HP:0033349",
        ]
        assert page.total == 1040 and page.more_available

    def test_offset_must_align_with_pages(self, fake_http):
        with pytest.raises(ValueError, match="multiple"):
            OLSEntitySearchAPI(http=fake_http({})).search("x", page_size=5, offset=3)

    def test_lookup_by_curie_synonym(self, fake_http):
        http = fake_http({f"{OLS}/v2/entities": "ols2_lookup_HP_0002197"})
        concept = OLSEntitySearchAPI(http=http).lookup("hpo:0002197")
        assert http.params["search"] == "HP:0002197"
        assert http.params["exactMatch"] is True
        assert http.params["ontologyId"] == "hp"
        assert concept.code == "HP:0002197"
        assert concept.iri == HP_0002197
        assert concept.display == "Generalized-onset seizure"

    def test_lookup_by_iri(self, fake_http):
        http = fake_http({f"{OLS}/v2/entities": "ols2_lookup_HP_0002197"})
        concept = OLSEntitySearchAPI(http=http).lookup(HP_0002197)
        assert http.params["iri"] == HP_0002197
        assert "search" not in http.params
        assert concept.code == "HP:0002197"

    def test_lookup_miss(self, fake_http):
        http = fake_http({f"{OLS}/v2/entities": {"elements": []}})
        assert OLSEntitySearchAPI(http=http).lookup("HP:0000000") is None


class TestHierarchy:
    @pytest.fixture
    def http(self, fake_http):
        return fake_http(
            {
                f"{OLS}/v2/entities": "ols2_lookup_HP_0002197",
                f"{TERMS}/children": "olsd_children_HP_0002197",
                f"{TERMS}/descendants": "olsd_descendants_HP_0002197",
            }
        )

    def test_children(self, http):
        result = OLSHierarchyAPI(http=http).children("HP:0002197")
        assert result.direct
        assert result.parent.code == "HP:0002197"
        assert [c.code for c in result] == ["HP:0002121", "HP:0032677"]
        assert result.url == f"{TERMS}/children"
        assert http.params == {"page": 0, "size": 500}

    def test_descendants(self, http):
        result = OLSHierarchyAPI(http=http).descendants("HP:0002197")
        assert not result.direct
        assert len(result) == 20
        assert {c.prefix for c in result} == {"HP"}
        assert all(c.source == "olsd" for c in result)

    def test_fetches_every_page(self, fake_http):
        def page(n, total_pages, codes):
            terms = [
                {
                    "obo_id": f"HP:{c}",
                    "iri": f"http://purl.obolibrary.org/obo/HP_{c}",
                    "label": c,
                    "ontology_prefix": "HP",
                }
                for c in codes
            ]
            return {
                "_embedded": {"terms": terms},
                "page": {"number": n, "totalPages": total_pages},
            }

        http = fake_http(
            {
                f"{OLS}/v2/entities": "ols2_lookup_HP_0002197",
                f"{TERMS}/descendants": [page(0, 2, ["1", "2"]), page(1, 2, ["3"])],
            }
        )
        result = OLSHierarchyAPI(http=http).descendants("HP:0002197")
        assert [c.code for c in result] == ["HP:1", "HP:2", "HP:3"]
        assert [p["page"] for p in http.calls_to("/descendants")] == [0, 1]

    def test_unknown_term(self, fake_http):
        http = fake_http({f"{OLS}/v2/entities": {"elements": []}})
        with pytest.raises(LookupError):
            OLSHierarchyAPI(http=http).descendants("HP:0000000")


def test_pages_stop_when_exhausted(fake_http):
    def payload(start, n, total):
        docs = [
            {"obo_id": f"HP:{i}", "iri": f"iri:{i}", "label": str(i)}
            for i in range(start, start + n)
        ]
        return {"response": {"docs": docs, "numFound": total}}

    http = fake_http(
        {f"{OLS}/search": [payload(0, 2, 5), payload(2, 2, 5), payload(4, 1, 5)]}
    )
    pages = list(OLSSearchAPI(http=http).pages("x", page_size=2))
    assert [len(p) for p in pages] == [2, 2, 1]
    assert [p["start"] for _, p in http.calls] == [0, 2, 4]
    assert not pages[-1].more_available


def test_hierarchy_folds_edam_subdomains(fake_http):
    edam = "http://edamontology.org/topic_0080"
    terms = f"{OLS}/ontologies/edam/terms/{quote(quote(edam, safe=''), safe='')}"
    http = fake_http(
        {
            f"{OLS}/v2/entities": "ols2_lookup_EDAM_topic_0080",
            f"{terms}/children": "olsd_children_EDAM_topic_0080",
        }
    )
    result = OLSHierarchyAPI(http=http).children(edam)
    # OLS returns EDAM_topic:0102 here, but EDAM:topic_0102 from search.
    assert result.parent.code == "edam:topic_0080"
    assert result.skipped == 0
    assert [c.code for c in result][:2] == ["edam:topic_0102", "edam:topic_0157"]


@pytest.mark.parametrize(
    "obo_id, ontology_prefix, expected",
    [
        ("EDAM_topic:0102", "EDAM", "EDAM:topic_0102"),
        ("EDAM:topic_0102", "EDAM", "EDAM:topic_0102"),
        ("UBERON:0000955", "HP", "UBERON:0000955"),  # imported, untouched
        ("NCBITaxon:9606", "NCBITAXON", "NCBITaxon:9606"),
        (None, "HP", None),
    ],
)
def test_fold_subdomain(obo_id, ontology_prefix, expected):
    from term_wyrm.apis.ols import _fold_subdomain

    assert _fold_subdomain(obo_id, ontology_prefix) == expected
