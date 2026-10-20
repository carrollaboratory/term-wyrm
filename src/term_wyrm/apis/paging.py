"""Translate a row offset and page size into each API's paging parameters.

Callers always page in rows (``offset``, ``page_size``); these strategies hide
whether the API wants a row offset or a page number.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


class Paging(ABC):
    @abstractmethod
    def params(self, offset: int, page_size: int) -> dict[str, int]:
        """Query parameters requesting this page."""


@dataclass(frozen=True)
class OffsetPaging(Paging):
    """The API takes a row offset directly (OLS search: ``start``/``rows``)."""

    offset_param: str
    size_param: str

    def params(self, offset, page_size):
        return {self.offset_param: offset, self.size_param: page_size}


@dataclass(frozen=True)
class PagePaging(Paging):
    """The API takes a page number (OLS v2: ``page``/``size``, 0-based)."""

    page_param: str
    size_param: str
    first_page: int = 0

    def params(self, offset, page_size):
        if offset % page_size:
            raise ValueError(
                f"offset {offset} must be a multiple of page_size {page_size} "
                "for page-numbered APIs"
            )
        return {
            self.page_param: offset // page_size + self.first_page,
            self.size_param: page_size,
        }
