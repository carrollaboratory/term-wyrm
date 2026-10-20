"""UMLS (Unified Medical Language System) UTS search adapter.

Search pages by 1-based ``pageNumber``. (The UTS docs say paging is not
supported; recorded responses show it is, with ``recCount`` as the total.)
"""

import os

from term_wyrm.apis.base import SearchAPI
from term_wyrm.apis.http import JsonClient
from term_wyrm.apis.paging import PagePaging
from term_wyrm.model import RawTerm
from term_wyrm.vocabulary import VocabularyManager

API_KEY_ENV = "UMLS_API_KEY"


class MissingApiKey(RuntimeError):
    pass


class UMLSSearchAPI(SearchAPI):
    api_id = "umls"
    family = "UMLS"
    name = "Unified Medical Language System"
    base_url = "https://uts-ws.nlm.nih.gov/rest"
    paging = PagePaging(page_param="pageNumber", size_param="pageSize", first_page=1)
    # Probed 2026-10: pageSize=1000 returned all 636 results; 500 is a safe cap.
    max_page_size = 500

    def __init__(
        self,
        vocabularies: VocabularyManager | None = None,
        http: JsonClient | None = None,
        api_key: str | None = None,
    ) -> None:
        super().__init__(vocabularies, http)
        self._api_key = api_key

    @property
    def api_key(self) -> str:
        key = self._api_key or os.environ.get(API_KEY_ENV)
        if not key:
            raise MissingApiKey(f"Set {API_KEY_ENV} or pass api_key= to query UMLS")
        return key

    @property
    def endpoint(self):
        return f"{self.base_url}/search/current"

    def query_params(self, text, vocs):
        # returnIdType=code returns source-vocabulary codes rather than CUIs.
        params = {"string": text, "returnIdType": "code", "apiKey": self.api_key}
        if vocs:
            params["sabs"] = ",".join(self.ontology_filter(vocs))
        return params

    def extract_records(self, payload):
        results = payload.get("result", {}).get("results", [])
        # The docs describe a {"ui": "NONE"} placeholder for empty searches;
        # current responses return an empty list, but filter it just in case.
        return [r for r in results if r.get("ui") != "NONE"]

    def extract_total(self, payload):
        return payload.get("result", {}).get("recCount")

    def parse_record(self, record):
        return RawTerm(
            prefix=record.get("rootSource"),
            code=record.get("ui"),
            iri=record.get("uri"),
            display=record.get("name"),
        )
