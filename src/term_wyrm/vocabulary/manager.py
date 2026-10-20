import logging
from collections.abc import Iterable, Iterator, Mapping
from functools import cache

from term_wyrm.vocabulary.coding import Coding, CodingError
from term_wyrm.vocabulary.curie import Curie
from term_wyrm.vocabulary.vocabulary import Origin, Vocabulary

logger = logging.getLogger(__name__)


class VocabularyConflict(ValueError):
    """A prefix, synonym, or system is claimed by two different vocabularies."""


def system_key(system: str) -> str:
    """Index key for a system URL: stored data mixes ``http``/``https`` and
    trailing slashes, so both are ignored when matching."""
    system = system.strip()
    scheme, sep, rest = system.partition("://")
    if sep and scheme.lower() in ("http", "https"):
        system = rest
    return system.rstrip("/")


class VocabularyManager:
    """Registry of vocabularies with case-insensitive prefix/synonym lookup.

    Name lookups ignore case and system lookups ignore ``http``/``https`` and
    trailing slashes (``system_key``); anything emitted uses
    ``Vocabulary.prefix`` and ``Vocabulary.system`` verbatim.
    """

    def __init__(self, vocabularies: Iterable[Vocabulary] = ()):
        self._vocabularies: dict[str, Vocabulary] = {}  # preferred prefix
        self._by_name: dict[str, Vocabulary] = {}  # casefolded prefix/synonym
        self._by_system: dict[str, Vocabulary] = {}  # system_key(system)
        for voc in vocabularies:
            self.add(voc)

    # --- registration -------------------------------------------------------

    def add(self, voc: Vocabulary) -> Vocabulary:
        # Check every claim before indexing anything, so a conflict leaves the
        # manager unchanged.
        for name in voc.names:
            self._check_claim(self._by_name, name.casefold(), voc, "name")
        for system in voc.systems:
            self._check_claim(self._by_system, system_key(system), voc, "system")

        self._vocabularies[voc.prefix] = voc
        for name in voc.names:
            self._by_name[name.casefold()] = voc
        for system in voc.systems:
            self._by_system[system_key(system)] = voc
        return voc

    def add_synonym(self, voc: Vocabulary, synonym: str) -> None:
        key = synonym.casefold()
        self._check_claim(self._by_name, key, voc, "name")
        if key not in self._by_name:
            voc.synonyms.append(synonym)
            self._by_name[key] = voc

    def add_system(self, voc: Vocabulary, system: str) -> None:
        key = system_key(system)
        self._check_claim(self._by_system, key, voc, "system")
        if key not in self._by_system:
            voc.alt_systems.append(system)
            self._by_system[key] = voc

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
        return self._by_system.get(system_key(system))

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

    # --- codings from outside (user files, stored data) ---------------------

    def harmonize_coding(
        self, code: str, system: str | None = None, *, strict: bool = True
    ) -> Coding:
        """Rewrite a code/system pair to the preferred CURIE and main system.

        The vocabulary comes from the code's CURIE prefix. A bare code (older
        data) takes it from ``system`` instead. Raises CodingError when neither
        identifies a known vocabulary, or when the code has an unknown prefix
        (even if the system is known: the prefix may be a typo or part of the
        code).

        If the prefix and a known system name different vocabularies, strict
        mode raises; otherwise the prefix wins, with a warning. An unknown
        system next to a known prefix is just replaced.
        """
        code = code.strip()
        system = system.strip() if system else None
        if not code:
            raise CodingError(code, system, "empty code")
        by_system = self.by_system(system) if system else None

        if ":" not in code:
            if by_system is None:
                reason = "unknown system" if system else "bare code and no system"
                raise CodingError(code, system, reason)
            return Coding(f"{by_system.prefix}:{code}", by_system.system, by_system)

        curie = Curie.try_parse(code)
        if curie is None:
            raise CodingError(code, system, "malformed CURIE")
        voc = self.resolve(curie.prefix)
        if voc is None:
            raise CodingError(code, system, f"unknown prefix {curie.prefix!r}")
        if by_system is not None and by_system is not voc:
            message = (
                f"prefix is {voc.prefix!r} but the system is {by_system.prefix!r}'s"
            )
            if strict:
                raise CodingError(code, system, message)
            logger.warning("%s (%s): %s; using the prefix", code, system, message)
        return Coding(f"{voc.prefix}:{curie.local_id}", voc.system, voc)


@cache
def default_vocabularies() -> VocabularyManager:
    """The packaged vocabularies, loaded once.

    Shared across callers; build your own manager if you need to modify it.
    """
    from term_wyrm.vocabulary.loaders import load

    return load()
