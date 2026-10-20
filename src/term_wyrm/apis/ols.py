"""Ontology Lookup Service (EBI OLS4) adapters.

- ``ols``:  /api/search            free-text search (row offset paging)
- ``ols2``: /api/v2/entities       entity search; best for exact code lookup
- ``olsd``: /api/ontologies/...    descendants / children of a term
"""

import logging
from typing import Any
from urllib.parse import quote

from term_wyrm.apis.base import OntologyAPI, SearchAPI
from term_wyrm.apis.http import JsonClient, redact_url
from term_wyrm.apis.paging import OffsetPaging, PagePaging
from term_wyrm.model import Concept, Hierarchy, RawTerm
from term_wyrm.vocabulary import Curie, VocabularyManager

logger = logging.getLogger(__name__)


def _texts(value: Any) -> tuple[str, ...]:
    """Flatten OLS text fields: a string, a list of strings, or v2's
    ``{"value": ...}`` reification objects."""
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, dict):
        return _texts(value.get("value"))
    return tuple(text for item in value for text in _texts(item))


def _first(value: Any) -> str | None:
    texts = _texts(value)
    return texts[0] if texts else None


def _prefix_of(code: str | None, fallback: str | None) -> str | None:
    """The term's own prefix. OLS reports the *hosting* ontology's prefix
    separately, which is wrong for imported terms (UBERON terms inside HP)."""
    curie = Curie.try_parse(code) if code else None
    return curie.prefix if curie else fallback


def _fold_subdomain(obo_id: str | None, ontology_prefix: str | None) -> str | None:
    """Undo the hierarchy endpoints' sub-domain form: ``EDAM_topic:0102``
    becomes ``EDAM:topic_0102``, matching what search returns.

    Only applies when the CURIE prefix is the hosting ontology's prefix plus a
    suffix, so imported terms (``UBERON:...`` inside HP) are left alone.
    """
    curie = Curie.try_parse(obo_id) if obo_id else None
    if not curie or not ontology_prefix:
        return obo_id
    base, sep, subdomain = curie.prefix.partition("_")
    if sep and subdomain and base.casefold() == ontology_prefix.casefold():
        return f"{base}:{subdomain}_{curie.local_id}"
    return obo_id


class OLSMixin:
    family = "OLS"
    base_url = "https://www.ebi.ac.uk/ols4/api"

    def ontology_filter(self, vocs):
        # OLS ontology ids are lowercase: hp, mondo, snomed, ncbitaxon.
        return [name.lower() for name in super().ontology_filter(vocs)]

    @staticmethod
    def parse_v1_term(record: dict[str, Any]) -> RawTerm:
        """Term records from /api/search and the v1 hierarchy endpoints."""
        ontology_prefix = record.get("ontology_prefix")
        obo_id = _fold_subdomain(record.get("obo_id"), ontology_prefix)
        code = obo_id or record.get("short_form")
        return RawTerm(
            prefix=_prefix_of(obo_id, ontology_prefix),
            code=code,
            iri=record.get("iri"),
            display=_first(record.get("label")),
            description=_texts(record.get("description")),
        )


class OLSSearchAPI(OLSMixin, SearchAPI):
    api_id = "ols"
    name = "Ontology Lookup Service"
    paging = OffsetPaging(offset_param="start", size_param="rows")

    @property
    def endpoint(self):
        return f"{self.base_url}/search"

    def query_params(self, text, vocs):
        params = {"q": text}
        if vocs:
            params["ontology"] = ",".join(self.ontology_filter(vocs))
        return params

    def extract_records(self, payload):
        return payload.get("response", {}).get("docs", [])

    def extract_total(self, payload):
        return payload.get("response", {}).get("numFound")

    def parse_record(self, record):
        return self.parse_v1_term(record)


class OLSEntitySearchAPI(OLSMixin, SearchAPI):
    api_id = "ols2"
    name = "Ontology Lookup Service V2"
    paging = PagePaging(page_param="page", size_param="size", first_page=0)

    @property
    def endpoint(self):
        return f"{self.base_url}/v2/entities"

    def query_params(self, text, vocs):
        # Only the defining ontology's copy of a term, not every importer's.
        params = {"search": text, "isDefiningOntology": True}
        if vocs:
            params["ontologyId"] = ",".join(self.ontology_filter(vocs))
        return params

    def extract_records(self, payload):
        return payload.get("elements", [])

    def extract_total(self, payload):
        return payload.get("totalElements")

    def parse_record(self, record):
        return RawTerm(
            prefix=_prefix_of(
                record.get("curie"), record.get("ontologyPreferredPrefix")
            ),
            code=record.get("curie") or record.get("shortForm"),
            iri=record.get("iri"),
            display=_first(record.get("label")),
            description=_texts(record.get("definition")),
        )

    def lookup(self, term: str) -> Concept | None:
        """Find exactly one term by CURIE (any known prefix) or IRI."""
        term = term.strip()
        params: dict[str, Any] = {"isDefiningOntology": True, "size": 10}
        curie = None
        if term.startswith(("http://", "https://", "urn:")):
            params["iri"] = term
        else:
            curie = self.vocabularies.canonical(term)
            voc = self.vocabularies[curie.prefix]
            params["search"] = self.query_text(term)
            params["exactMatch"] = True
            params["ontologyId"] = self.ontology_filter([voc])[0]

        payload = self.get_json(self.endpoint, params)
        concepts, _ = self.to_concepts(self.extract_records(payload))
        return next((c for c in concepts if c.iri == term or c.curie == curie), None)


class OLSHierarchyAPI(OLSMixin, OntologyAPI):
    api_id = "olsd"
    name = "Ontology Lookup Service hierarchy"
    page_size = 500

    def __init__(
        self,
        vocabularies: VocabularyManager | None = None,
        http: JsonClient | None = None,
        entities: OLSEntitySearchAPI | None = None,
    ) -> None:
        super().__init__(vocabularies, http)
        self.entities = entities or OLSEntitySearchAPI(self.vocabularies, self.http)

    def parse_record(self, record):
        return self.parse_v1_term(record)

    def descendants(self, term: str, *, direct: bool = False) -> Hierarchy:
        """All descendants of ``term`` (a CURIE or IRI); only the immediate
        children when ``direct`` is true."""
        parent = self.entities.lookup(term)
        if parent is None:
            raise LookupError(f"OLS has no term {term!r}")

        ontology = self.ontology_filter([self.vocabularies[parent.prefix]])[0]
        # OLS requires the IRI to be URL-encoded twice in the path.
        iri = quote(quote(parent.iri, safe=""), safe="")
        relation = "children" if direct else "descendants"
        url = f"{self.base_url}/ontologies/{ontology}/terms/{iri}/{relation}"

        records, page = [], 0
        while True:
            payload = self.get_json(url, {"page": page, "size": self.page_size})
            records.extend(payload.get("_embedded", {}).get("terms", []))
            page += 1
            if page >= payload.get("page", {}).get("totalPages", 0):
                break

        concepts, skipped = self.to_concepts(records)
        return Hierarchy(
            parent=parent,
            concepts=concepts,
            direct=direct,
            url=redact_url(url),
            source=self.api_id,
            skipped=skipped,
        )

    def children(self, term: str) -> Hierarchy:
        return self.descendants(term, direct=True)
