import logging
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from typing import Any, ClassVar

from term_wyrm.apis.http import HttpClient, JsonClient, build_url, redact_url
from term_wyrm.apis.paging import Paging
from term_wyrm.model import Concept, RawTerm, SearchPage
from term_wyrm.vocabulary import (
    Curie,
    Vocabulary,
    VocabularyManager,
    default_vocabularies,
)

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, type["OntologyAPI"]] = {}


class OntologyAPI(ABC):
    """Common behaviour for every API adapter.

    Subclasses only pull fields out of the API's records (``parse_record``);
    deciding the preferred prefix and system happens here, in ``harmonize``.
    Concrete subclasses that set ``api_id`` register themselves for
    ``get_api``.
    """

    api_id: ClassVar[str]
    family: ClassVar[str]  # key into Vocabulary.api_prefixes: "OLS", "UMLS"
    name: ClassVar[str]
    base_url: ClassVar[str]

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        api_id = cls.__dict__.get("api_id")
        if api_id:
            if api_id in _REGISTRY:
                raise ValueError(f"Duplicate api_id {api_id!r}")
            _REGISTRY[api_id] = cls

    def __init__(
        self,
        vocabularies: VocabularyManager | None = None,
        http: JsonClient | None = None,
    ) -> None:
        self.vocabularies = vocabularies or default_vocabularies()
        self.http = http or HttpClient()

    # --- vocabulary names, as this API spells them --------------------------

    def api_prefix(self, voc: Vocabulary) -> str:
        return voc.api_prefix(self.family)

    def ontology_filter(self, vocs: Iterable[Vocabulary]) -> list[str]:
        """Names to send when restricting a query to these vocabularies.

        An empty API prefix means "bare codes" for queries, so it falls back to
        the preferred prefix here.
        """
        return [self.api_prefix(v) or v.prefix for v in vocs]

    def resolve_all(self, names: Iterable[str]) -> list[Vocabulary]:
        """Look up vocabularies by prefix or synonym; raises KeyError if unknown."""
        return [self.vocabularies[name] for name in names]

    def query_text(self, text: str) -> str:
        """Rewrite a CURIE with a known prefix into this API's form."""
        curie = Curie.try_parse(text)
        if curie and curie.prefix in self.vocabularies:
            return self.vocabularies.to_api(curie, self.family)
        return text.strip()

    # --- records -> Concepts ------------------------------------------------

    @abstractmethod
    def parse_record(self, record: dict[str, Any]) -> RawTerm:
        """Extract fields from one API record. No vocabulary logic here."""

    def harmonize(self, raw: RawTerm) -> Concept | None:
        voc = self.vocabularies.resolve(raw.prefix) if raw.prefix else None
        if voc is None or not raw.code:
            logger.debug(
                "%s: dropping record with unknown vocabulary: %s", self.api_id, raw
            )
            return None
        return Concept(
            curie=Curie(voc.prefix, self._local_id(raw.code, voc)),
            system=voc.system,
            iri=raw.iri,
            display=raw.display,
            description=raw.description,
            source=self.api_id,
        )

    def _local_id(self, code: str, voc: Vocabulary) -> str:
        """Strip the code's prefix if it is one of ``voc``'s names."""
        curie = Curie.try_parse(code)
        if curie and self.vocabularies.resolve(curie.prefix) is voc:
            return curie.local_id
        return code

    def to_concepts(
        self, records: Iterable[dict[str, Any]]
    ) -> tuple[list[Concept], int]:
        """Harmonize and de-duplicate records; also returns how many were skipped."""
        concepts, seen, skipped = [], set(), 0
        for record in records:
            concept = self.harmonize(self.parse_record(record))
            if concept is None:
                skipped += 1
                continue
            key = concept.iri or concept.code
            if key in seen:
                continue
            seen.add(key)
            concepts.append(concept)
        return concepts, skipped

    def get_json(self, url: str, params: dict | None = None) -> Any:
        return self.http.get_json(url, params)

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


class SearchAPI(OntologyAPI):
    """An API that answers free-text or code searches, one page at a time."""

    paging: ClassVar[Paging]
    max_page_size: ClassVar[int] = 500
    default_page_size: ClassVar[int] = 25

    @property
    @abstractmethod
    def endpoint(self) -> str: ...

    @abstractmethod
    def query_params(self, text: str, vocs: list[Vocabulary]) -> dict[str, Any]:
        """Parameters for the query itself, excluding paging."""

    @abstractmethod
    def extract_records(self, payload: Any) -> list[dict[str, Any]]: ...

    @abstractmethod
    def extract_total(self, payload: Any) -> int | None: ...

    def search(
        self,
        text: str,
        ontologies: Iterable[str] = (),
        *,
        page_size: int | None = None,
        offset: int = 0,
    ) -> SearchPage:
        """Search for ``text`` (free text or a CURIE), optionally restricted to
        ``ontologies`` (any prefix or synonym the vocabulary manager knows)."""
        page_size = page_size or self.default_page_size
        if not 0 < page_size <= self.max_page_size:
            raise ValueError(
                f"{self.api_id}: page_size must be 1..{self.max_page_size}"
            )
        if offset < 0:
            raise ValueError("offset must be >= 0")

        vocs = self.resolve_all(ontologies)
        params = {
            **self.query_params(self.query_text(text), vocs),
            **self.paging.params(offset, page_size),
        }
        payload = self.get_json(self.endpoint, params)
        records = self.extract_records(payload)
        total = self.extract_total(payload)
        concepts, skipped = self.to_concepts(records)

        if total is not None:
            more = offset + len(records) < total
        else:
            more = len(records) == page_size
        return SearchPage(
            concepts=concepts,
            offset=offset,
            page_size=page_size,
            total=total,
            more_available=more,
            url=redact_url(build_url(self.endpoint, params)),
            source=self.api_id,
            skipped=skipped,
            raw_count=len(records),
        )

    def pages(
        self,
        text: str,
        ontologies: Iterable[str] = (),
        *,
        page_size: int | None = None,
        offset: int = 0,
        max_pages: int | None = None,
    ) -> Iterator[SearchPage]:
        """Yield successive pages until the API runs out (or ``max_pages``)."""
        ontologies = list(ontologies)
        count = 0
        while max_pages is None or count < max_pages:
            page = self.search(text, ontologies, page_size=page_size, offset=offset)
            yield page
            count += 1
            if not page.more_available or page.raw_count == 0:
                return
            offset += page.page_size


def get_api(api_id: str, **kwargs) -> OntologyAPI:
    """Instantiate a registered adapter by id (``"ols"``, ``"umls"``, ...)."""
    try:
        cls = _REGISTRY[api_id.lower()]
    except KeyError:
        raise KeyError(
            f"Unknown API {api_id!r}; available: {', '.join(sorted(_REGISTRY))}"
        ) from None
    return cls(**kwargs)


def available_apis() -> dict[str, type[OntologyAPI]]:
    return dict(_REGISTRY)
