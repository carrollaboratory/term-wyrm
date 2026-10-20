"""``term-wyrm`` command line.

    term-wyrm search seizure HP:0001250 -o HP,MONDO
    term-wyrm descendants HP:0002197 --parent -f csv --output tree.csv
    term-wyrm children "generalized-onset seizure" -o HP

Rich tables need the optional extra (``term-wyrm[rich]``); without it, tables
are plain text.

Exit status: 0 results found, 1 nothing found, 2 bad arguments, 3 an API
failed (any results that did arrive are still written).
"""

import argparse
import contextlib
import logging
import os
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TextIO

from term_wyrm.apis import ApiError
from term_wyrm.apis.umls import API_KEY_ENV
from term_wyrm.model import ApiFailure
from term_wyrm.output import (
    HIERARCHY_COLUMNS,
    SEARCH_COLUMNS,
    Row,
    hierarchy_rows,
    search_rows,
    write_csv,
    write_json,
    write_plain_table,
)
from term_wyrm.service import SearchService

OK, NOT_FOUND, USAGE, API_FAILED = 0, 1, 2, 3
FORMATS = ("table", "rich", "plain", "csv", "json")

SEARCH_TABLE = ("searched_code", "response_code", "display", "system", "api")
HIERARCHY_TABLE = ("parent_code", "descendant_code", "display", "system")


class UsageError(Exception):
    pass


def _split(values: Iterable[str] | None, sep: str = ",") -> list[str]:
    """Flatten repeated and delimited options: ``-o HP,MONDO -o mesh``."""
    return [part.strip() for v in values or () for part in v.split(sep) if part.strip()]


def default_apis() -> str:
    return "ols,ols2,umls" if os.environ.get(API_KEY_ENV) else "ols,ols2"


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-f",
        "--format",
        choices=FORMATS,
        help="table (Rich if installed, else plain), rich, plain, csv, or json. "
        "Defaults to table, or to csv/json from the --output extension.",
    )
    common.add_argument("--output", type=Path, help="write here instead of stdout")
    common.add_argument("-v", "--verbose", action="store_true", help="debug logging")

    parser = argparse.ArgumentParser(
        prog="term-wyrm",
        description="Search ontology APIs; results use standardized CURIE prefixes.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    search = commands.add_parser(
        "search", parents=[common], help="search one or more terms or CURIEs"
    )
    search.add_argument(
        "keywords", nargs="+", help="free text or CURIEs ('|' also separates)"
    )
    search.add_argument(
        "-o",
        "--ontologies",
        action="append",
        help="restrict to these prefixes, comma-separated or repeated",
    )
    search.add_argument(
        "-a",
        "--apis",
        action="append",
        help=f"APIs to query in order (default: ols,ols2, plus umls if "
        f"{API_KEY_ENV} is set)",
    )
    search.add_argument("-n", "--page-size", type=int, help="results per API")
    search.add_argument(
        "--offset", type=int, default=0, help="rows to skip (a multiple of -n)"
    )
    search.set_defaults(run=run_search)

    for name, direct in (("descendants", False), ("children", True)):
        tree = commands.add_parser(
            name,
            parents=[common],
            help=f"{'direct children' if direct else 'all descendants'} of a term "
            "(OLS)",
        )
        tree.add_argument("term", help="a CURIE, an IRI, or free text with -o")
        tree.add_argument(
            "-o", "--ontology", help="ontology for a free-text term, e.g. HP"
        )
        tree.add_argument(
            "-p", "--parent", action="store_true", help="include the parent term"
        )
        tree.set_defaults(run=run_hierarchy, direct=direct)
    return parser


def output_format(args: argparse.Namespace) -> str:
    if args.format:
        return args.format
    if args.output:
        return "json" if args.output.suffix.lower() == ".json" else "csv"
    return "table"


def write(
    args: argparse.Namespace,
    file: TextIO,
    rows: list[Row],
    columns: Sequence[str],
    table_columns: Sequence[str],
    data: object,
    title: str,
) -> None:
    fmt = output_format(args)
    if fmt == "table":
        fmt = "rich" if _have_rich() else "plain"
    if fmt == "csv":
        write_csv(rows, columns, file)
    elif fmt == "json":
        write_json(data, file)
    elif fmt == "plain":
        write_plain_table(rows, table_columns, file)
    else:
        write_rich_table(rows, table_columns, file, title)


def _have_rich() -> bool:
    try:
        import rich  # noqa: F401
    except ImportError:
        return False
    return True


def write_rich_table(
    rows: list[Row], columns: Sequence[str], file: TextIO, title: str
) -> None:
    from rich.console import Console
    from rich.table import Table

    table = Table(title=title, expand=True, row_styles=["yellow", "green"])
    for column in columns:
        table.add_column(column.replace("_", " ").title())
    for row in rows:
        table.add_row(*(" ".join(row.get(c, "").split()) for c in columns))
    Console(file=file).print(table)


@contextlib.contextmanager
def open_output(path: Path | None):
    if path is None:
        yield sys.stdout
    else:
        with path.open("w", encoding="utf-8", newline="") as file:
            yield file


def report(failures: Iterable[ApiFailure]) -> None:
    seen = set()
    for failure in failures:
        if (failure.source, failure.error) not in seen:
            seen.add((failure.source, failure.error))
            print(f"warning: {failure.source}: {failure.error}", file=sys.stderr)


def run_search(args: argparse.Namespace) -> int:
    keywords = _split(args.keywords, "|")
    ontologies = _split(args.ontologies)
    apis = _split(args.apis or [default_apis()])
    try:
        service = SearchService(apis)
        results = service.search_many(
            keywords, ontologies, page_size=args.page_size, offset=args.offset
        )
    except (KeyError, ValueError, TypeError) as e:
        raise UsageError(e.args[0] if e.args else str(e)) from e

    with open_output(args.output) as file:
        write(
            args,
            file,
            search_rows(results),
            SEARCH_COLUMNS,
            SEARCH_TABLE,
            {query: result.to_dict() for query, result in results.items()},
            "Search Results",
        )
    failures = [f for result in results.values() for f in result.failures]
    report(failures)
    if failures:
        return API_FAILED
    return OK if any(results.values()) else NOT_FOUND


def run_hierarchy(args: argparse.Namespace) -> int:
    try:
        tree = SearchService(["ols2"]).descendants(
            args.term, args.ontology, direct=args.direct
        )
    except (KeyError, ValueError) as e:
        raise UsageError(e.args[0] if e.args else str(e)) from e
    except LookupError as e:
        print(f"term-wyrm: {e}", file=sys.stderr)
        return NOT_FOUND

    relation = "Children" if args.direct else "Descendants"
    with open_output(args.output) as file:
        write(
            args,
            file,
            hierarchy_rows(tree, include_parent=args.parent),
            HIERARCHY_COLUMNS,
            HIERARCHY_TABLE,
            tree.to_dict(),
            f"{relation} of {tree.parent.code} {tree.parent.display or ''}".strip(),
        )
    return OK if len(tree) else NOT_FOUND


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if output_format(args) == "rich" and not _have_rich():
        parser.error("-f rich needs Rich: pip install 'term-wyrm[rich]'")
    try:
        return args.run(args)
    except UsageError as e:
        parser.error(str(e))
    except ApiError as e:
        print(f"term-wyrm: {e}", file=sys.stderr)
        return API_FAILED


if __name__ == "__main__":
    sys.exit(main())
