from dataclasses import dataclass, field
from enum import StrEnum


class SourceType(StrEnum):
    OWL = "OWL"
    OMOP = "OMOP"
    FHIR = "FHIR"


class Origin(StrEnum):
    """Where a Vocabulary's definition came from."""

    DETAILS = "details"  # fully described in vocabulary_details.csv
    LEGACY = "legacy"  # stub built from the legacy prefix/system lookup


@dataclass(eq=False)
class Vocabulary:
    """A code system, identified by its preferred prefix.

    ``prefix`` is the preferred CURIE prefix and is always emitted exactly as
    written. ``synonyms`` and ``alt_systems`` only help with lookups; use
    VocabularyManager to add them so its indexes stay in sync.
    """

    prefix: str
    system: str
    name: str | None = None
    description: str | None = None
    uri: str | None = None
    source_type: SourceType | None = None
    source_filename: str | None = None
    synonyms: list[str] = field(default_factory=list)
    alt_systems: list[str] = field(default_factory=list)
    # API family ("OLS", "UMLS") -> the prefix that API uses. An empty string
    # is meaningful: that API uses bare codes with no prefix.
    api_prefixes: dict[str, str] = field(default_factory=dict)
    origin: Origin = Origin.DETAILS

    @property
    def is_stub(self) -> bool:
        return self.origin is Origin.LEGACY

    @property
    def systems(self) -> list[str]:
        return [self.system, *self.alt_systems]

    @property
    def names(self) -> list[str]:
        """Every name lookups accept: prefix, synonyms, and API-specific
        prefixes (so UMLS's ``NCI`` maps back to ``NCIT``)."""
        api_names = [name for name in self.api_prefixes.values() if name]
        return [self.prefix, *self.synonyms, *api_names]

    def api_prefix(self, family: str) -> str:
        """The prefix the given API family uses, defaulting to the preferred one."""
        return self.api_prefixes.get(family.upper(), self.prefix)

    def __repr__(self) -> str:
        return f"Vocabulary(prefix={self.prefix!r}, system={self.system!r})"
