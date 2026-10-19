import pytest

from term_wyrm import Curie, Origin, Vocabulary, VocabularyConflict, VocabularyManager


@pytest.fixture
def manager():
    return VocabularyManager(
        [
            Vocabulary(
                prefix="HP",
                system="http://purl.obolibrary.org/obo/hp.owl",
                synonyms=["HPO"],
                api_prefixes={"UMLS": "HPO"},
            ),
            Vocabulary(
                prefix="snomedct",
                system="http://snomed.info/sct",
                synonyms=["SNOMED", "SCT"],
                api_prefixes={"OLS": "SNOMED"},
            ),
            Vocabulary(
                prefix="omim", system="https://omim.org", api_prefixes={"UMLS": ""}
            ),
        ]
    )


@pytest.mark.parametrize("name", ["HP", "hp", "Hp", "HPO", "hpo", " HP "])
def test_resolve_ignores_case(manager, name):
    assert manager.resolve(name).prefix == "HP"


def test_unknown_prefix(manager):
    assert manager.resolve("MONDO") is None
    assert "MONDO" not in manager
    with pytest.raises(KeyError):
        manager["MONDO"]


def test_canonical_keeps_preferred_case(manager):
    assert manager.canonical("SNOMED:84757009") == Curie("snomedct", "84757009")
    assert str(manager.canonical("hpo:0001250")) == "HP:0001250"


@pytest.mark.parametrize(
    "curie, family, expected",
    [
        ("HP:0001250", "UMLS", "HPO:0001250"),
        ("HPO:0001250", "OLS", "HP:0001250"),
        ("snomedct:84757009", "OLS", "SNOMED:84757009"),
        ("SNOMEDCT:84757009", "UMLS", "snomedct:84757009"),
        ("OMIM:163950", "UMLS", "163950"),  # empty API prefix -> bare code
        ("OMIM:163950", "ols", "omim:163950"),  # family is case-insensitive
    ],
)
def test_to_api(manager, curie, family, expected):
    assert manager.to_api(curie, family) == expected


def test_by_system_includes_alt_systems(manager):
    hp, intl = manager["HP"], "http://purl.obolibrary.org/obo/hp/hp-international.owl"
    manager.add_system(hp, intl)
    assert manager.by_system(intl) is hp
    assert hp.system == "http://purl.obolibrary.org/obo/hp.owl"  # primary unchanged


def test_add_rejects_conflicting_names_without_partial_registration(manager):
    clash = Vocabulary(prefix="NEW", system="http://new", synonyms=["hpo"])
    with pytest.raises(VocabularyConflict):
        manager.add(clash)
    assert "NEW" not in manager
    assert manager.by_system("http://new") is None


def test_add_rejects_conflicting_system(manager):
    with pytest.raises(VocabularyConflict):
        manager.add(Vocabulary(prefix="NEW", system="http://snomed.info/sct"))


def test_add_synonym_conflict(manager):
    with pytest.raises(VocabularyConflict):
        manager.add_synonym(manager["omim"], "SCT")


class TestMergeLegacy:
    def test_known_prefix_gains_system(self, manager):
        voc = manager.merge_legacy("SNOMED", "file:///snomed-inferred.owl")
        assert voc.prefix == "snomedct"
        assert manager.by_system("file:///snomed-inferred.owl") is voc

    def test_known_system_gains_synonym(self, manager):
        voc = manager.merge_legacy("MIM", "https://omim.org")
        assert voc.prefix == "omim"
        assert manager.resolve("mim") is voc

    def test_unknown_becomes_stub(self, manager):
        voc = manager.merge_legacy("MP", "http://purl.obolibrary.org/obo/mp.owl")
        assert voc.origin is Origin.LEGACY and voc.is_stub
        assert manager.resolve("mp") is voc

    def test_prefix_and_system_disagree(self, manager):
        with pytest.raises(VocabularyConflict):
            manager.merge_legacy("HP", "http://snomed.info/sct")

    def test_repeat_is_noop(self, manager):
        manager.merge_legacy("HP", "http://purl.obolibrary.org/obo/hp.owl")
        assert manager["HP"].alt_systems == []
        assert manager["HP"].synonyms == ["HPO"]
