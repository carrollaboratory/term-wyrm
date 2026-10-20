"""term-wyrm: guardian of terms. A refactor of search-dragon."""

from importlib.metadata import PackageNotFoundError, version

from term_wyrm.model import ApiFailure, Concept, Hierarchy, SearchPage, SearchResult
from term_wyrm.service import SearchService
from term_wyrm.vocabulary import (
    Coding,
    CodingError,
    Curie,
    Origin,
    SourceType,
    Vocabulary,
    VocabularyConflict,
    VocabularyManager,
    default_vocabularies,
)

try:
    __version__ = version("term-wyrm")
except PackageNotFoundError:  # running from a source tree that isn't installed
    __version__ = "0.0.0+unknown"

__all__ = [
    "__version__",
    "ApiFailure",
    "Coding",
    "CodingError",
    "Concept",
    "Curie",
    "Hierarchy",
    "Origin",
    "SearchPage",
    "SearchResult",
    "SearchService",
    "SourceType",
    "Vocabulary",
    "VocabularyConflict",
    "VocabularyManager",
    "default_vocabularies",
]
