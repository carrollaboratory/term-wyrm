"""Result types shared by every API adapter."""

from dataclasses import dataclass, field

from term_wyrm.vocabulary import Curie


@dataclass(frozen=True, slots=True)
class RawTerm:
    """Fields pulled out of one API record, before vocabulary normalization.

    ``prefix`` is whatever the API called the vocabulary and ``code`` is the
    API's identifier, which may or may not carry that prefix.
    """

    prefix: str | None
    code: str | None
    iri: str | None
    display: str | None
    description: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Concept:
    """A term with its preferred CURIE and the vocabulary's system."""

    curie: Curie
    system: str
    iri: str | None
    display: str | None
    description: tuple[str, ...] = ()
    source: str = ""  # api_id of the adapter that produced it

    @property
    def code(self) -> str:
        return str(self.curie)

    @property
    def prefix(self) -> str:
        return self.curie.prefix

    def to_dict(self) -> dict:
        """The record shape search-dragon returned."""
        return {
            "code": self.code,
            "system": self.system,
            "code_iri": self.iri or "",
            "display": self.display or "",
            "description": list(self.description),
            "ontology_prefix": self.prefix,
        }


@dataclass(frozen=True, slots=True)
class SearchPage:
    """One page of results.

    ``offset`` and ``page_size`` are in result rows for every API. ``total`` is
    the API's count of matching records, when it reports one. ``skipped``
    counts records dropped because their vocabulary was unknown.
    """

    concepts: list[Concept]
    offset: int
    page_size: int
    total: int | None
    more_available: bool
    url: str  # API keys redacted
    source: str
    skipped: int = 0
    raw_count: int = field(default=0, repr=False)

    def __iter__(self):
        return iter(self.concepts)

    def __len__(self) -> int:
        return len(self.concepts)


@dataclass(frozen=True, slots=True)
class Hierarchy:
    """Every descendant (or, when ``direct``, every child) of ``parent``."""

    parent: Concept
    concepts: list[Concept]
    direct: bool
    url: str
    source: str
    skipped: int = 0

    def to_dict(self) -> dict:
        return {
            "parent": self.parent.to_dict(),
            "direct": self.direct,
            "results": [c.to_dict() for c in self.concepts],
            "results_count": len(self.concepts),
            "search_query": self.url,
        }

    def __iter__(self):
        return iter(self.concepts)

    def __len__(self) -> int:
        return len(self.concepts)


@dataclass(frozen=True, slots=True)
class ApiFailure:
    """An API that could not answer; the others' results are still returned."""

    source: str
    error: str
    url: str | None = None  # API keys redacted

    def to_dict(self) -> dict:
        return {"api": self.source, "error": self.error, "url": self.url}


@dataclass(frozen=True, slots=True)
class SearchResult:
    """One query sent to several APIs.

    ``concepts`` merges every page in API order, keeping the first concept for
    each CURIE (so an OLS IRI wins over UMLS's for the same HP code). ``pages``
    keeps each API's own page, keyed by ``api_id``.
    """

    query: str
    concepts: list[Concept]
    pages: dict[str, SearchPage]
    failures: list[ApiFailure] = field(default_factory=list)

    @property
    def more_available(self) -> bool:
        return any(page.more_available for page in self.pages.values())

    @property
    def skipped(self) -> int:
        return sum(page.skipped for page in self.pages.values())

    def counts_by_prefix(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for concept in self.concepts:
            counts[concept.prefix] = counts.get(concept.prefix, 0) + 1
        return counts

    def to_dict(self) -> dict:
        """JSON-ready; the field names follow search-dragon's response."""
        return {
            "query": self.query,
            "results": [c.to_dict() for c in self.concepts],
            "results_per_ontology": self.counts_by_prefix(),
            "results_count": len(self.concepts),
            "more_results_available": self.more_available,
            "search_queries": {api: page.url for api, page in self.pages.items()},
            "failures": [f.to_dict() for f in self.failures],
        }

    def __iter__(self):
        return iter(self.concepts)

    def __len__(self) -> int:
        return len(self.concepts)
