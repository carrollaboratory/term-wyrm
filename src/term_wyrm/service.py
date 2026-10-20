"""Run one query across several APIs and merge the results."""

import logging
from collections.abc import Iterable, Sequence

from term_wyrm.apis.base import SearchAPI, get_api
from term_wyrm.apis.http import ApiError, HttpClient, JsonClient
from term_wyrm.apis.ols import OLSEntitySearchAPI, OLSHierarchyAPI
from term_wyrm.apis.umls import MissingApiKey
from term_wyrm.model import ApiFailure, Concept, Hierarchy, SearchResult
from term_wyrm.vocabulary import Curie, VocabularyManager, default_vocabularies

logger = logging.getLogger(__name__)

DEFAULT_APIS = ("ols", "ols2", "umls")

# Failures that belong to one API; anything else is a bug or bad input and
# propagates.
API_FAILURES = (ApiError, MissingApiKey)


class SearchService:
    """Searches several APIs with one set of vocabularies and one HTTP client.

    ``apis`` are api ids (``"ols"``, ``"umls"``) or ready-made ``SearchAPI``
    instances, e.g. ``UMLSSearchAPI(api_key=...)``. They are queried in order,
    and that order decides which API's copy of a concept is kept when results
    are merged.
    """

    def __init__(
        self,
        apis: Iterable[str | SearchAPI] = DEFAULT_APIS,
        *,
        vocabularies: VocabularyManager | None = None,
        http: JsonClient | None = None,
    ) -> None:
        self.vocabularies = vocabularies or default_vocabularies()
        self.http = http or HttpClient()
        self.apis = [self._make_api(api) for api in apis]
        ids = [api.api_id for api in self.apis]
        if len(set(ids)) != len(ids):
            raise ValueError(f"Duplicate APIs: {ids}")
        self._hierarchy: OLSHierarchyAPI | None = None

    def _make_api(self, api: str | SearchAPI) -> SearchAPI:
        if isinstance(api, str):
            api = get_api(api, vocabularies=self.vocabularies, http=self.http)
        if not isinstance(api, SearchAPI):
            raise TypeError(f"{api.api_id!r} is not a search API")
        return api

    @property
    def hierarchy(self) -> OLSHierarchyAPI:
        """The OLS hierarchy adapter, sharing this service's ols2 if it has one."""
        if self._hierarchy is None:
            entities = next(
                (a for a in self.apis if isinstance(a, OLSEntitySearchAPI)), None
            )
            self._hierarchy = OLSHierarchyAPI(self.vocabularies, self.http, entities)
        return self._hierarchy

    def search(
        self,
        text: str,
        ontologies: Sequence[str] = (),
        *,
        page_size: int | None = None,
        offset: int = 0,
    ) -> SearchResult:
        """Send ``text`` to every API and merge the pages.

        An API that fails is reported in ``failures``; the rest still answer.
        Unknown ontology names raise KeyError before anything is sent.
        """
        ontologies = list(ontologies)
        for name in ontologies:
            self.vocabularies[name]

        pages, failures = {}, []
        for api in self.apis:
            try:
                page = api.search(text, ontologies, page_size=page_size, offset=offset)
            except API_FAILURES as e:
                failures.append(self._failure(api, e))
                continue
            pages[api.api_id] = page

        concepts, seen = [], set()
        for page in pages.values():
            for concept in page:
                if concept.curie not in seen:
                    seen.add(concept.curie)
                    concepts.append(concept)
        return SearchResult(
            query=text, concepts=concepts, pages=pages, failures=failures
        )

    def search_many(
        self, texts: Iterable[str], ontologies: Sequence[str] = (), **kwargs
    ) -> dict[str, SearchResult]:
        """``search`` each text in turn, keyed by the text."""
        return {text: self.search(text, ontologies, **kwargs) for text in texts}

    def first_match(
        self,
        text: str,
        ontology: str,
        *,
        page_size: int | None = None,
        max_pages: int = 10,
        apis: Iterable[SearchAPI] | None = None,
    ) -> Concept | None:
        """The first result for ``text`` that belongs to ``ontology``.

        A search restricted to one ontology can still return other
        vocabularies' terms (OLS includes imported terms), so this pages on
        until it finds one, trying each API in turn. Returns None only when
        every API answered without a match; otherwise the first failure is
        raised.
        """
        target = self.vocabularies[ontology]
        errors = []
        for api in self.apis if apis is None else apis:
            try:
                for page in api.pages(
                    text, [target.prefix], page_size=page_size, max_pages=max_pages
                ):
                    for concept in page:
                        if concept.prefix == target.prefix:
                            return concept
            except API_FAILURES as e:
                self._failure(api, e)
                errors.append(e)
        if errors:
            raise errors[0]
        return None

    def descendants(
        self, term: str, ontology: str | None = None, *, direct: bool = False
    ) -> Hierarchy:
        """Descendants (or, when ``direct``, children) of ``term``.

        ``term`` is a CURIE, an IRI, or free text. Free text needs
        ``ontology`` and uses its first OLS match as the parent.
        """
        if not self._is_identifier(term):
            if ontology is None:
                raise ValueError(f"{term!r} is not a CURIE or IRI; pass ontology=")
            match = self.first_match(term, ontology, apis=[self.hierarchy.entities])
            if match is None or not match.iri:
                raise LookupError(f"OLS has no {ontology} term matching {term!r}")
            term = match.iri
        return self.hierarchy.descendants(term, direct=direct)

    def children(self, term: str, ontology: str | None = None) -> Hierarchy:
        return self.descendants(term, ontology, direct=True)

    def _is_identifier(self, term: str) -> bool:
        term = term.strip()
        if term.startswith(("http://", "https://", "urn:")):
            return True
        curie = Curie.try_parse(term)
        return curie is not None and curie.prefix in self.vocabularies

    @staticmethod
    def _failure(api: SearchAPI, error: Exception) -> ApiFailure:
        logger.warning("%s failed: %s", api.api_id, error)
        return ApiFailure(api.api_id, str(error), getattr(error, "url", None))

    def __repr__(self) -> str:
        return f"SearchService({[api.api_id for api in self.apis]})"
