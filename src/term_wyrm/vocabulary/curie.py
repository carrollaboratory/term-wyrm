from dataclasses import dataclass
from typing import Self


@dataclass(frozen=True, slots=True)
class Curie:
    """A compact URI: ``prefix:local_id``.

    Purely syntactic; whether the prefix is the preferred one is the
    VocabularyManager's concern.
    """

    prefix: str
    local_id: str

    @classmethod
    def parse(cls, text: str) -> Self:
        """Split on the first colon. Raises ValueError if there is no prefix."""
        prefix, sep, local_id = text.strip().partition(":")
        if not sep or not prefix or not local_id:
            raise ValueError(f"Not a CURIE: {text!r}")
        return cls(prefix, local_id)

    @classmethod
    def try_parse(cls, text: str) -> Self | None:
        try:
            return cls.parse(text)
        except ValueError:
            return None

    def __str__(self) -> str:
        return f"{self.prefix}:{self.local_id}"
