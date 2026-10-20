import logging
from collections.abc import Iterable, Iterator, Mapping
from functools import cache

from term_wyrm.vocabulary.curie import Curie
from term_wyrm.vocabulary.vocabulary import Origin, Vocabulary

logger = logging.getLogger(__name__)


class VocabularyConflict(ValueError):
    """A prefix, synonym, or system is claimed by two different vocabularies."""


class VocabularyManager:
    """Registry of vocabularies with case-insensitive prefix/synonym lookup.

    Lookups ignore case; anything emitted uses ``Vocabulary.prefix`` verbatim.
    """

    def __init__(self, vocabularies: Iterable[Vocabulary] = ()):
        self._vocabularies: dict[str, Vocabulary] = {}  # preferred prefix
        self._by_name: dict[str, Vocabulary] = {}  # casefolded prefix/synonym
        self._by_system: dict[str, Vocabulary] = {}
        for voc in vocabularies:
            self.add(voc)

    # --- registration -------------------------------------------------------

    def add(self, voc: Vocabulary) -> Vocabulary:
        # Check every claim before indexing anything, so a conflict leaves the
        # manager unchanged.
        for name in voc.names:
            self._check_claim(self._by_name, name.casefold(), voc, "name")
        for system in voc.systems:
            self._check_claim(self._by_system, system, voc, "system")

        self._vocabularies[voc.prefix] = voc
        for name in voc.names:
            self._by_name[name.casefold()] = voc
        for system in voc.systems:
            self._by_system[system] = voc
        return voc

    def add_synonym(self, voc: Vocabulary, synonym: str) -> None:
        key = synonym.casefold()
        self._check_claim(self._by_name, key, voc, "name")
        if key not in self._by_name:
            voc.synonyms.append(synonym)
            self._by_name[key] = voc

    def add_system(self, voc: Vocabulary, system: str) -> None:
        self._check_claim(self._by_system, system, voc, "system")
        if system not in self._by_system:
            voc.alt_systems.append(system)
            self._by_system[system] = voc

    def add_api_prefix(self, voc: Vocabulary, family: str, api_prefix: str) -> None:
        """Record what an API family calls ``voc``. An existing entry wins, so
        vocabulary_details.csv takes precedence over the legacy file."""
        family = family.upper()
        current = voc.api_prefixes.get(family)
        if current is not None:
            if current != api_prefix:
                logger.warning(
                    "Ignoring %s:%s for %r; already %s:%s",
                    family,
                    api_prefix,
                    voc.prefix,
                    family,
                    current,
                )
            return
        if api_prefix:
            key = api_prefix.casefold()
            self._check_claim(self._by_name, key, voc, "name")
            self._by_name[key] = voc
        voc.api_prefixes[family] = api_prefix

    @staticmethod
    def _check_claim(index, key, voc, kind):
        owner = index.get(key)
        if owner is not None and owner is not voc:
            raise VocabularyConflict(
                f"{kind} {key!r} is claimed by both {owner.prefix!r} and {voc.prefix!r}"
            )

    def merge_legacy(
        self,
        prefix: str,
        system: str,
        api_prefixes: Mapping[str, str] | None = None,
    ) -> Vocabulary:
        """Fold one legacy ``prefix,system`` row into the registry.

        A known prefix gains the system; a known system gains the prefix as a
        synonym; otherwise a stub vocabulary is created. Any ``api_prefixes``
        are then added to whichever vocabulary the row landed on.
        """
        by_name = self.resolve(prefix)
        by_system = self.by_system(system)
        if by_name and by_system and by_name is not by_system:
            raise VocabularyConflict(
                f"legacy row {prefix},{system} matches {by_name.prefix!r} by prefix "
                f"but {by_system.prefix!r} by system"
            )
        if by_name:
            self.add_system(by_name, system)
            voc = by_name
        elif by_system:
            self.add_synonym(by_system, prefix)
            voc = by_system
        else:
            voc = self.add(
                Vocabulary(prefix=prefix, system=system, origin=Origin.LEGACY)
            )
        for family, api_prefix in (api_prefixes or {}).items():
            self.add_api_prefix(voc, family, api_prefix)
        return voc

    # --- lookup -------------------------------------------------------------

    def resolve(self, name: str) -> Vocabulary | None:
        """Find a vocabulary by preferred prefix, synonym, or API prefix,
        ignoring case."""
        return self._by_name.get(name.strip().casefold())

    def by_system(self, system: str) -> Vocabulary | None:
        return self._by_system.get(system.strip())

    def __getitem__(self, name: str) -> Vocabulary:
        voc = self.resolve(name)
        if voc is None:
            raise KeyError(f"Unknown vocabulary prefix: {name!r}")
        return voc

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and self.resolve(name) is not None

    def __iter__(self) -> Iterator[Vocabulary]:
        return iter(self._vocabularies.values())

    def __len__(self) -> int:
        return len(self._vocabularies)

    # --- CURIE translation --------------------------------------------------

    def canonical(self, curie: str | Curie) -> Curie:
        """Rewrite a CURIE to use the preferred prefix. Raises KeyError if unknown."""
        if isinstance(curie, str):
            curie = Curie.parse(curie)
        return Curie(self[curie.prefix].prefix, curie.local_id)

    def to_api(self, curie: str | Curie, family: str) -> str:
        """Render a CURIE the way an API family expects it in a query.

        An empty API prefix means that API uses bare codes, e.g. OMIM in UMLS.
        """
        if isinstance(curie, str):
            curie = Curie.parse(curie)
        api_prefix = self[curie.prefix].api_prefix(family)
        return f"{api_prefix}:{curie.local_id}" if api_prefix else curie.local_id


@cache
def default_vocabularies() -> VocabularyManager:
    """The packaged vocabularies, loaded once.

    Shared across callers; build your own manager if you need to modify it.
    """
    from term_wyrm.vocabulary.loaders import load

    return load()
