import pytest

from term_wyrm import Curie


def test_parse_splits_on_first_colon():
    assert Curie.parse("HP:0001250") == Curie("HP", "0001250")
    assert Curie.parse(" NCIT:C3262 ") == Curie("NCIT", "C3262")
    assert Curie.parse("x:a:b") == Curie("x", "a:b")


@pytest.mark.parametrize("text", ["HP0001250", ":0001250", "HP:", ""])
def test_parse_rejects_non_curies(text):
    with pytest.raises(ValueError):
        Curie.parse(text)
    assert Curie.try_parse(text) is None


def test_str_round_trips():
    assert str(Curie.parse("snomedct:84757009")) == "snomedct:84757009"
