"""Flatten results into rows and write them as CSV, JSON, or a plain table.

Standard library only, so the library can use these too. The CLI's Rich table
lives in ``term_wyrm.cli``.
"""

import csv
import json
from collections.abc import Iterable, Mapping
from typing import TextIO

from term_wyrm.model import Concept, Hierarchy, SearchResult

# Column names match search-dragon's CSV output.
SEARCH_COLUMNS = (
    "api",
    "searched_code",
    "response_code",
    "display",
    "description",
    "system",
    "code_iri",
    "ontology_prefix",
)
HIERARCHY_COLUMNS = (
    "api",
    "parent_code",
    "descendant_code",
    "display",
    "description",
    "system",
    "code_iri",
    "ontology_prefix",
)

Row = dict[str, str]


def _concept_fields(concept: Concept) -> dict[str, str]:
    return {
        "api": concept.source,
        "display": concept.display or "",
        "description": "\n".join(concept.description),
        "system": concept.system,
        "code_iri": concept.iri or "",
        "ontology_prefix": concept.prefix,
    }


def search_rows(results: Mapping[str, SearchResult]) -> list[Row]:
    """One row per concept. A query with no results still gets one row, with
    an empty ``response_code``, so it isn't silently missing from the file."""
    rows = []
    for query, result in results.items():
        if not result.concepts:
            rows.append(dict.fromkeys(SEARCH_COLUMNS, "") | {"searched_code": query})
        for concept in result:
            rows.append(
                {
                    "searched_code": query,
                    "response_code": concept.code,
                    **_concept_fields(concept),
                }
            )
    return rows


def hierarchy_rows(tree: Hierarchy, *, include_parent: bool = False) -> list[Row]:
    """One row per descendant; the parent first, with no ``parent_code``, when
    ``include_parent``."""
    rows = []
    if include_parent:
        rows.append(
            {
                "parent_code": "",
                "descendant_code": tree.parent.code,
                **_concept_fields(tree.parent),
            }
        )
    for concept in tree:
        rows.append(
            {
                "parent_code": tree.parent.code,
                "descendant_code": concept.code,
                **_concept_fields(concept),
            }
        )
    return rows


def write_csv(rows: Iterable[Row], columns: Iterable[str], file: TextIO) -> None:
    writer = csv.DictWriter(file, fieldnames=list(columns), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)


def write_json(data: object, file: TextIO) -> None:
    json.dump(data, file, indent=2, ensure_ascii=False)
    file.write("\n")


def write_plain_table(
    rows: Iterable[Row], columns: Iterable[str], file: TextIO, *, max_width: int = 60
) -> None:
    """Fixed-width text columns; long cells are cut to ``max_width``."""
    columns = list(columns)

    def cell(value: str) -> str:
        value = " ".join(value.split())
        return value if len(value) <= max_width else value[: max_width - 1] + "…"

    table = [columns] + [[cell(row.get(c, "")) for c in columns] for row in rows]
    widths = [max(len(line[i]) for line in table) for i in range(len(columns))]
    for n, line in enumerate(table):
        print(
            "  ".join(v.ljust(w) for v, w in zip(line, widths, strict=True)).rstrip(),
            file=file,
        )
        if n == 0:
            print("  ".join("-" * w for w in widths), file=file)
