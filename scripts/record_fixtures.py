"""Record live API responses as test fixtures in tests/fixtures/.

    uv run python scripts/record_fixtures.py            # OLS fixtures
    UMLS_API_KEY=... uv run python scripts/record_fixtures.py umls
    UMLS_API_KEY=... uv run python scripts/record_fixtures.py umls-limits  # probe

Responses are trimmed so fixtures stay small, and API keys are never written.
Re-recording changes the data, so expect to update test expectations.
"""

import json
import sys
from pathlib import Path
from urllib.parse import quote

from term_wyrm.apis.http import ApiError, HttpClient
from term_wyrm.apis.umls import API_KEY_ENV

OLS = "https://www.ebi.ac.uk/ols4/api"
UMLS = "https://uts-ws.nlm.nih.gov/rest/search/current"
OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
HP_TERM = "http://purl.obolibrary.org/obo/HP_0002197"
EDAM_TOPIC = "http://edamontology.org/topic_0080"


def double_quote(iri):
    """OLS hierarchy paths need the IRI URL-encoded twice."""
    return quote(quote(iri, safe=""), safe="")


def keep_docs(payload, n, extra=lambda doc: False):
    """Keep the first n search docs plus any matching ``extra``."""
    docs = payload["response"]["docs"]
    payload["response"]["docs"] = [d for i, d in enumerate(docs) if i < n or extra(d)]
    return payload


def drop_v2_noise(payload):
    """v2 entities carry dozens of raw OWL properties; keep what we read."""
    keep = {
        "curie",
        "iri",
        "label",
        "definition",
        "definedBy",
        "ontologyId",
        "ontologyPreferredPrefix",
        "shortForm",
        "isDefiningOntology",
        "type",
    }
    payload["elements"] = [
        {k: v for k, v in e.items() if k in keep} for e in payload["elements"]
    ]
    return payload


def drop_links(payload):
    """Hierarchy terms each carry a block of HAL links we never read."""
    for term in payload.get("_embedded", {}).get("terms", []):
        term.pop("_links", None)
    payload.pop("_links", None)
    return payload


def ols_fixtures(http):
    terms = f"{OLS}/ontologies/hp/terms/{double_quote(HP_TERM)}"
    return {
        # Includes an imported UBERON term reported with ontology_prefix "HP".
        "ols_search_brain_hp": keep_docs(
            http.get_json(
                f"{OLS}/search", {"q": "brain", "ontology": "hp", "rows": 40}
            ),
            3,
            lambda d: not d["obo_id"].startswith("HP:"),
        ),
        "ols_search_epilepsy_snomed": http.get_json(
            f"{OLS}/search", {"q": "epilepsy", "ontology": "snomed", "rows": 3}
        ),
        "ols2_search_seizure_page1": drop_v2_noise(
            http.get_json(
                f"{OLS}/v2/entities",
                {
                    "search": "seizure",
                    "ontologyId": "hp,mondo",
                    "isDefiningOntology": True,
                    "page": 1,
                    "size": 5,
                },
            )
        ),
        "ols2_lookup_HP_0002197": drop_v2_noise(
            http.get_json(
                f"{OLS}/v2/entities",
                {
                    "search": "HP:0002197",
                    "exactMatch": True,
                    "isDefiningOntology": True,
                    "ontologyId": "hp",
                    "size": 10,
                },
            )
        ),
        "olsd_children_HP_0002197": drop_links(
            http.get_json(f"{terms}/children", {"page": 0, "size": 500})
        ),
        "olsd_descendants_HP_0002197": drop_links(
            http.get_json(f"{terms}/descendants", {"page": 0, "size": 500})
        ),
        # Hierarchy endpoints write EDAM ids as EDAM_topic:0102.
        "ols2_lookup_EDAM_topic_0080": drop_v2_noise(
            http.get_json(
                f"{OLS}/v2/entities",
                {"iri": EDAM_TOPIC, "isDefiningOntology": True, "size": 10},
            )
        ),
        "olsd_children_EDAM_topic_0080": drop_links(
            http.get_json(
                f"{OLS}/ontologies/edam/terms/{double_quote(EDAM_TOPIC)}/children",
                {"page": 0, "size": 500},
            )
        ),
    }


def umls_params(**params):
    import os

    key = os.environ.get(API_KEY_ENV) or sys.exit(f"{API_KEY_ENV} is not set")
    return {"returnIdType": "code", "apiKey": key, **params}


# "seizure" in these sources matches ~636 records, enough to exceed 200.
SEIZURE = {"string": "seizure", "sabs": "HPO,SNOMEDCT_US,MSH"}


def umls_fixtures(http):
    return {
        "umls_search_seizure": http.get_json(UMLS, umls_params(**SEIZURE)),
        # A larger page than the default 25.
        "umls_search_seizure_200": http.get_json(
            UMLS, umls_params(**SEIZURE, pageSize=200)
        ),
        "umls_search_none": http.get_json(
            UMLS, umls_params(string="zzzxqqnotaterm", sabs="HPO")
        ),
    }


def umls_page_limits(http):
    """Print how many results UMLS returns for each requested pageSize.

    Writes no fixtures. If a size returns fewer than requested while recCount
    is larger, UMLS is capping the page.
    """
    for size in (25, 200, 201, 500, 1000):
        try:
            payload = http.get_json(UMLS, umls_params(**SEIZURE, pageSize=size))
        except ApiError as e:
            print(f"pageSize={size:>4}: {e}")
            continue
        result = payload.get("result", {})
        print(
            f"pageSize={size:>4}: got {len(result.get('results', [])):>4} "
            f"(recCount={result.get('recCount')}, "
            f"echoed pageSize={payload.get('pageSize')})"
        )
    return {}


def main(which=("ols",)):
    http = HttpClient()
    OUT.mkdir(parents=True, exist_ok=True)
    groups = {
        "ols": ols_fixtures,
        "umls": umls_fixtures,
        "umls-limits": umls_page_limits,
    }
    for group in which:
        for name, payload in groups[group](http).items():
            path = OUT / f"{name}.json"
            path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
            n = len(payload.get("result", {}).get("results", []))
            note = f" ({n} results)" if name.startswith("umls") else ""
            print(f"wrote {path.relative_to(OUT.parent.parent)}{note}")


if __name__ == "__main__":
    main(sys.argv[1:] or ("ols",))
