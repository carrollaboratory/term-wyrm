"""Build a VocabularyManager from the CSV files.

``vocabulary_details.csv`` is authoritative. The legacy
``ftd_ontology_lookup.csv`` (``curie,system``) only adds synonyms, alternate
systems, and stub vocabularies for anything not otherwise described.
"""

import csv
import logging
import os
from collections.abc import Iterator
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import IO

from term_wyrm.vocabulary.manager import VocabularyManager
from term_wyrm.vocabulary.vocabulary import SourceType, Vocabulary

logger = logging.getLogger(__name__)

Source = str | os.PathLike | Traversable

DETAILS_FIELDS = (
    "name",
    "description",
    "prefix",
    "fhir_system",
    "uri",
    "source_type",
    "source_filename",
    "synonym",
    "api_preference",
)
LEGACY_FIELDS = ("curie", "system")

_DATA = files("term_wyrm.data")
DEFAULT_DETAILS = _DATA / "vocabulary_details.csv"
DEFAULT_LEGACY = _DATA / "ftd_ontology_lookup.csv"


def _open(source: Source) -> IO[str]:
    if isinstance(source, (str, os.PathLike)):
        return open(source, encoding="utf-8", newline="")
    return source.open("r", encoding="utf-8", newline="")


def _read_rows(source: Source, required: tuple[str, ...]) -> Iterator[dict[str, str]]:
    """Yield stripped CSV rows, rejecting missing columns and ragged rows."""
    with _open(source) as infile:
        reader = csv.DictReader(infile)
        missing = set(required) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{source}: missing columns {sorted(missing)}")
        for row in reader:
            # DictReader files extra fields under None and fills short rows with
            # None; both mean the row is malformed (usually an unquoted comma).
            if None in row or None in row.values():
                raise ValueError(
                    f"{source}:{reader.line_num}: expected {len(reader.fieldnames)} "
                    "fields; check for an unquoted comma"
                )
            yield {k: v.strip() for k, v in row.items()}


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_api_preference(value: str) -> dict[str, str]:
    """Parse ``"OLS:SNOMED,UMLS:HPO"`` into ``{"OLS": "SNOMED", "UMLS": "HPO"}``.

    ``"UMLS:"`` maps UMLS to an empty prefix (bare codes).
    """
    prefs = {}
    for item in _split(value):
        family, sep, prefix = item.partition(":")
        if not sep or not family.strip():
            raise ValueError(f"Malformed api_preference entry: {item!r}")
        prefs[family.strip().upper()] = prefix.strip()
    return prefs


def vocabulary_from_row(row: dict[str, str]) -> Vocabulary:
    prefix = row["prefix"]
    if not prefix or not row["fhir_system"]:
        raise ValueError(f"Vocabulary row needs a prefix and fhir_system: {row}")
    seen = {prefix.casefold()}
    synonyms = []
    for syn in _split(row["synonym"]):
        # Case variants of names already present add nothing; lookups ignore case.
        if syn.casefold() not in seen:
            seen.add(syn.casefold())
            synonyms.append(syn)
    return Vocabulary(
        prefix=prefix,
        system=row["fhir_system"],
        name=row["name"] or None,
        description=row["description"] or None,
        uri=row["uri"] or None,
        source_type=SourceType(row["source_type"]) if row["source_type"] else None,
        source_filename=row["source_filename"] or None,
        synonyms=synonyms,
        api_prefixes=parse_api_preference(row["api_preference"]),
    )


def read_details(source: Source) -> list[Vocabulary]:
    return [vocabulary_from_row(row) for row in _read_rows(source, DETAILS_FIELDS)]


def read_legacy(source: Source) -> list[tuple[str, str]]:
    return [
        (row["curie"], row["system"])
        for row in _read_rows(source, LEGACY_FIELDS)
        if row["curie"] and row["system"]
    ]


def backfill_legacy(manager: VocabularyManager, rows: list[tuple[str, str]]) -> None:
    """Merge legacy rows into ``manager`` in two passes.

    Pass 1 handles rows whose prefix is already known, so their systems are
    registered first. Pass 2 then merges the rest in file order, where a row
    can match one of those new systems (``LNC`` -> loinc via ``https://loinc.org/``)
    or a stub created earlier in the pass (``ORDO`` after ``ORPHANET``).
    """
    remaining = []
    for prefix, system in rows:
        if prefix in manager:
            manager.merge_legacy(prefix, system)
        else:
            remaining.append((prefix, system))

    stubs_before = len(manager)
    for prefix, system in remaining:
        manager.merge_legacy(prefix, system)
    logger.debug(
        "Legacy backfill: %d rows, %d stub vocabularies",
        len(rows),
        len(manager) - stubs_before,
    )


def load(
    details: Source = DEFAULT_DETAILS, legacy: Source | None = DEFAULT_LEGACY
) -> VocabularyManager:
    manager = VocabularyManager(read_details(details))
    if legacy is not None:
        backfill_legacy(manager, read_legacy(legacy))
    return manager
