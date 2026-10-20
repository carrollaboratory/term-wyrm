import logging

import pytest

from term_wyrm import (
    Coding,
    CodingError,
    Curie,
    Vocabulary,
    VocabularyManager,
    default_vocabularies,
)

HP_SYSTEM = "http://purl.obolibrary.org/obo/hp.owl"
SNOMED_SYSTEM = "http://snomed.info/sct"


@pytest.fixture
def manager():
    return VocabularyManager(
        [
            Vocabulary(
                prefix="HP",
                system=HP_SYSTEM,
                synonyms=["HPO"],
                alt_systems=["https://hpo.jax.org/"],
            ),
            Vocabulary(prefix="snomedct", system=SNOMED_SYSTEM, synonyms=["SNOMED"]),
        ]
    )


@pytest.mark.parametrize(
    ("code", "system"),
    [
        ("HP:0001250", None),
        ("hpo:0001250", None),
        (" HPO:0001250 ", HP_SYSTEM),
        ("HP:0001250", "https://hpo.jax.org/"),  # alternate system
        ("0001250", "https://purl.obolibrary.org/obo/hp.owl"),  # https variant
        ("0001250", "http://hpo.jax.org"),  # alternate, no slash
        ("HP:0001250", "https://outdated.example.org/hpo"),  # unknown system
        ("0001250", HP_SYSTEM),  # older bare code
        ("0001250", "https://hpo.jax.org/"),
    ],
)
def test_harmonizes_to_preferred_prefix_and_main_system(manager, code, system):
    coding = manager.harmonize_coding(code, system)
    assert coding == Coding("HP:0001250", HP_SYSTEM, manager["HP"])
    assert coding.curie == Curie("HP", "0001250")
    assert coding.vocabulary is manager["HP"]


@pytest.mark.parametrize(
    ("code", "system", "reason"),
    [
        ("", HP_SYSTEM, "empty code"),
        ("0001250", None, "bare code and no system"),
        ("0001250", "https://unknown.example.org", "unknown system"),
        ("FOO:0001250", None, "unknown prefix 'FOO'"),
        # A known system doesn't rescue an unknown prefix.
        ("FOO:0001250", HP_SYSTEM, "unknown prefix 'FOO'"),
        ("HP:", HP_SYSTEM, "malformed CURIE"),
        (":0001250", HP_SYSTEM, "malformed CURIE"),
    ],
)
def test_unmatched(manager, code, system, reason):
    with pytest.raises(CodingError) as error:
        manager.harmonize_coding(code, system)
    assert error.value.reason == reason
    assert error.value.code == code.strip()
    assert error.value.system == system
    assert isinstance(error.value, ValueError)


def test_conflict_is_an_error_when_strict(manager):
    with pytest.raises(CodingError, match="system is 'snomedct'"):
        manager.harmonize_coding("HP:0001250", SNOMED_SYSTEM)


def test_conflict_uses_the_prefix_when_lenient(manager, caplog):
    with caplog.at_level(logging.WARNING):
        coding = manager.harmonize_coding("HP:0001250", SNOMED_SYSTEM, strict=False)
    assert (coding.code, coding.system) == ("HP:0001250", HP_SYSTEM)
    assert "using the prefix" in caplog.text


def test_lenient_still_raises_when_unmatched(manager):
    with pytest.raises(CodingError):
        manager.harmonize_coding("FOO:1", None, strict=False)


@pytest.mark.parametrize(
    ("code", "system", "expected"),
    [
        ("SNOMEDCT:73211009", None, "snomedct:73211009"),
        ("ORPHANET:558", None, "ORDO:558"),  # legacy-only stub vocabulary
        ("NCI:C3171", None, "NCIT:C3171"),
        ("163950", "https://omim.org/", "omim:163950"),
        ("163950", "http://omim.org", "omim:163950"),
    ],
)
def test_packaged_vocabularies(code, system, expected):
    assert default_vocabularies().harmonize_coding(code, system).code == expected
