import pytest

from term_wyrm import Origin, SourceType, default_vocabularies
from term_wyrm.vocabulary import load
from term_wyrm.vocabulary.loaders import parse_api_preference, read_details

HEADER = (
    "name,description,prefix,fhir_system,uri,source_type,source_filename,"
    "synonym,api_preference\n"
)


@pytest.fixture
def write(tmp_path):
    def _write(name, text):
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        return path

    return _write


def test_parse_api_preference():
    assert parse_api_preference("") == {}
    assert parse_api_preference("UMLS:HPO") == {"UMLS": "HPO"}
    assert parse_api_preference("ols:SNOMED, UMLS:SNOMEDCT_US") == {
        "OLS": "SNOMED",
        "UMLS": "SNOMEDCT_US",
    }
    assert parse_api_preference("UMLS:") == {"UMLS": ""}
    with pytest.raises(ValueError):
        parse_api_preference("SNOMED")


def test_read_details_row(write):
    path = write(
        "v.csv",
        HEADER
        + "SNOMED CT,desc,snomedct,http://snomed.info/sct,http://snomed.info/id/,"
        'OMOP,,"snomedct,SNOMED,SCT,sct","OLS:SNOMED,UMLS:SNOMEDCT_US"\n',
    )
    [voc] = read_details(path)
    assert voc.prefix == "snomedct"
    assert voc.system == "http://snomed.info/sct"
    assert voc.source_type is SourceType.OMOP
    assert voc.source_filename is None
    assert voc.synonyms == ["SNOMED", "SCT"]  # prefix and case duplicates dropped
    assert voc.api_prefix("OLS") == "SNOMED"
    assert voc.api_prefix("UMLS") == "SNOMEDCT_US"


def test_unquoted_comma_is_rejected(write):
    path = write(
        "v.csv",
        HEADER + "SNOMED CT,d,snomedct,http://snomed.info/sct,u,,,SNOMED,OLS:SNOMED,"
        "UMLS:SNOMEDCT_US\n",
    )
    with pytest.raises(ValueError, match="unquoted comma"):
        read_details(path)


def test_missing_column_is_rejected(write):
    path = write("v.csv", "name,prefix\nx,y\n")
    with pytest.raises(ValueError, match="missing columns"):
        read_details(path)


def test_two_pass_backfill(write):
    details = write(
        "v.csv",
        HEADER
        + "LOINC,d,loinc,http://loinc.org,u,,,LOINC,\n"
        + "HPO,d,HP,http://purl.obolibrary.org/obo/hp.owl,u,,,HPO,UMLS:HPO\n",
    )
    # LNC precedes LOINC, and only matches loinc via the system LOINC adds.
    legacy = write(
        "l.csv",
        "curie,system\n"
        "LNC,https://loinc.org/\n"
        "LOINC,https://loinc.org/\n"
        "ORPHANET,http://www.orphadata.org/data/ORDO/ordo_orphanet.owl\n"
        "ORDO,http://www.orphadata.org/data/ORDO/ordo_orphanet.owl\n"
        "MP,http://purl.obolibrary.org/obo/mp/mp-international.owl\n"
        "MP,http://purl.obolibrary.org/obo/mp.owl\n",
    )
    m = load(details, legacy)

    assert m.resolve("LNC").prefix == "loinc"
    assert m["loinc"].alt_systems == ["https://loinc.org/"]
    assert m["loinc"].origin is Origin.DETAILS

    assert m.resolve("ordo") is m["ORPHANET"]
    assert m["ORPHANET"].prefix == "ORPHANET"
    assert m["ORPHANET"].is_stub

    assert m.by_system("http://purl.obolibrary.org/obo/mp.owl") is m["MP"]
    assert len(m) == 4  # loinc, HP, ORPHANET, MP


def test_legacy_api_preference(write):
    details = write(
        "v.csv",
        HEADER
        + "SNOMED CT,d,snomedct,http://snomed.info/sct,u,,,SNOMED,OLS:SNOMED\n"
        + "NCIT,d,NCIT,http://ncit.owl,u,,,,UMLS:NCI\n",
    )
    legacy = write(
        "l.csv",
        "curie,system,api_preference\n"
        "ORPHANET,http://ordo.owl,\n"
        'ORDO,http://ordo.owl,"OLS:ORDO"\n'
        "SNOMED,http://snomed.info/sct,OLS:SCT\n",  # details wins
    )
    m = load(details, legacy)
    orphanet = m["ORPHANET"]
    assert orphanet.api_prefix("OLS") == "ORDO"  # from a later row of the same stub
    assert m.to_api("ORPHANET:558", "OLS") == "ORDO:558"
    assert m["snomedct"].api_prefix("OLS") == "SNOMED"
    # API prefixes resolve inbound, too.
    assert m.resolve("NCI") is m["NCIT"]


def test_legacy_is_optional(write):
    details = write("v.csv", HEADER + "x,d,X,http://x,u,,,,\n")
    assert len(load(details, None)) == 1


@pytest.fixture(scope="module")
def vocab():
    return default_vocabularies()


class TestPackagedData:
    """Checks against the CSVs shipped in term_wyrm/data."""

    def test_is_cached(self, vocab):
        assert default_vocabularies() is vocab

    @pytest.mark.parametrize(
        "name, prefix",
        [
            ("HPO", "HP"),
            ("SNOMED", "snomedct"),
            ("SNOMEDCT_US", "snomedct"),
            ("MIM", "omim"),
            ("LNC", "loinc"),
            ("MDR", "meddra"),
            ("MSH", "mesh"),
            ("ncbitaxon", "NCBITaxon"),
            ("ORPHANET", "ORDO"),
            ("NCI", "NCIT"),
        ],
    )
    def test_synonyms_resolve_to_preferred_prefix(self, vocab, name, prefix):
        assert vocab[name].prefix == prefix

    def test_api_preferences(self, vocab):
        assert vocab["HP"].api_prefix("UMLS") == "HPO"
        assert vocab["snomedct"].api_prefix("OLS") == "SNOMED"
        assert vocab["snomedct"].api_prefix("UMLS") == "SNOMEDCT_US"
        assert vocab["omim"].api_prefix("UMLS") == ""
        assert vocab["MONDO"].api_prefix("OLS") == "MONDO"
        assert vocab["NCIT"].api_prefix("UMLS") == "NCI"
        assert vocab["ORPHANET"].api_prefix("OLS") == "ORDO"

    def test_details_vocabularies_are_not_stubs(self, vocab):
        details = [v for v in vocab if not v.is_stub]
        assert len(details) == 31
        assert all(v.name for v in details)

    def test_legacy_alt_systems(self, vocab):
        hp = vocab.by_system("http://purl.obolibrary.org/obo/hp/hp-international.owl")
        assert hp is vocab["HP"]
