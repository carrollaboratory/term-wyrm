from dataclasses import dataclass, field

from term_wyrm.vocabulary.curie import Curie
from term_wyrm.vocabulary.vocabulary import Vocabulary


class CodingError(ValueError):
    """A code/system pair that can't be harmonized to a known vocabulary."""

    def __init__(self, code: str, system: str | None, reason: str):
        super().__init__(f"{code!r} ({system or 'no system'}): {reason}")
        self.code = code
        self.system = system
        self.reason = reason


@dataclass(frozen=True, slots=True)
class Coding:
    """A code as a CURIE with the preferred prefix, and its vocabulary's
    main system."""

    code: str
    system: str
    vocabulary: Vocabulary = field(compare=False, repr=False)

    @property
    def curie(self) -> Curie:
        return Curie.parse(self.code)
