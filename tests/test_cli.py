import csv
import io
import json
from urllib.parse import quote

import pytest

from term_wyrm import SearchService, cli
from term_wyrm.output import SEARCH_COLUMNS, write_plain_table

OLS = "https://www.ebi.ac.uk/ols4/api"
OLS2 = f"{OLS}/v2/entities"
UMLS = "https://uts-ws.nlm.nih.gov/rest/search/current"
HP_0002197 = "http://purl.obolibrary.org/obo/HP_0002197"
TERMS = f"{OLS}/ontologies/hp/terms/{quote(quote(HP_0002197, safe=''), safe='')}"
EMPTY_OLS2 = {"elements": [], "totalElements": 0}


@pytest.fixture
def routes():
    return {
        f"{OLS}/search": "ols_search_brain_hp",
        OLS2: "ols2_search_seizure_page1",
        UMLS: "umls_search_seizure",
        f"{TERMS}/descendants": "olsd_descendants_HP_0002197",
        f"{TERMS}/children": "olsd_children_HP_0002197",
    }


@pytest.fixture
def http(fake_http, routes, monkeypatch):
    """Route every SearchService the CLI builds through FakeHttp."""
    fake = fake_http(routes)
    monkeypatch.setattr(
        cli, "SearchService", lambda apis: SearchService(apis, http=fake)
    )
    monkeypatch.delenv("UMLS_API_KEY", raising=False)
    return fake


def run(capsys, *argv):
    code = cli.main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


class TestSearch:
    def test_csv(self, http, capsys):
        code, out, err = run(capsys, "search", "seizure", "-a", "ols2", "-f", "csv")
        assert code == cli.OK and err == ""
        rows = list(csv.DictReader(io.StringIO(out)))
        assert tuple(rows[0]) == SEARCH_COLUMNS
        assert rows[0] == {
            "api": "ols2",
            "searched_code": "seizure",
            "response_code": "HP:0002349",
            "display": rows[0]["display"],
            "description": rows[0]["description"],
            "system": "http://purl.obolibrary.org/obo/hp.owl",
            "code_iri": "http://purl.obolibrary.org/obo/HP_0002349",
            "ontology_prefix": "HP",
        }
        assert len(rows) == 5

    def test_options(self, http, capsys):
        run(
            capsys,
            *("search", "HP:0001250|brain", "-o", "HPO,mondo", "-o", "mesh"),
            *("-a", "ols", "-n", "10", "--offset", "20", "-f", "csv"),
        )
        first, second = http.calls_to("/search")
        assert first == {
            "q": "HP:0001250",
            "ontology": "hp,mondo,mesh",
            "start": 20,
            "rows": 10,
        }
        assert second["q"] == "brain"

    def test_json(self, http, capsys):
        _, out, _ = run(capsys, "search", "seizure", "-a", "ols2,umls", "-f", "json")
        data = json.loads(out)
        assert list(data) == ["seizure"]
        assert data["seizure"]["results_count"] == 5
        assert data["seizure"]["failures"][0]["api"] == "umls"

    def test_failed_api_warns_and_exits_3(self, http, capsys):
        code, out, err = run(
            capsys, "search", "seizure", "-a", "ols2,umls", "-f", "csv"
        )
        assert code == cli.API_FAILED
        assert err.count("warning: umls:") == 1
        assert "HP:0002349" in out  # ols2's results still written

    def test_umls_by_default_only_with_a_key(self, http, capsys, monkeypatch):
        run(capsys, "search", "seizure", "-f", "csv")
        assert http.calls_to("/search/current") == []
        monkeypatch.setenv("UMLS_API_KEY", "k")
        code, _, _ = run(capsys, "search", "seizure", "-f", "csv")
        assert code == cli.OK
        assert len(http.calls_to("/search/current")) == 1

    def test_no_results(self, http, capsys):
        http.routes[OLS2] = EMPTY_OLS2
        code, out, _ = run(capsys, "search", "zzz", "-a", "ols2", "-f", "csv")
        assert code == cli.NOT_FOUND
        [row] = list(csv.DictReader(io.StringIO(out)))
        assert row["searched_code"] == "zzz" and row["response_code"] == ""

    @pytest.mark.parametrize(
        "argv",
        [
            ("search", "x", "-o", "NOTAVOCAB"),
            ("search", "x", "-a", "nope"),
            ("search", "x", "-a", "olsd"),
            ("search", "x", "-a", "ols2", "-n", "5", "--offset", "3"),
        ],
    )
    def test_bad_arguments_exit_2(self, http, capsys, argv):
        with pytest.raises(SystemExit) as exit:
            cli.main(list(argv))
        assert exit.value.code == cli.USAGE
        assert http.calls == []

    def test_output_file_format_from_extension(self, http, capsys, tmp_path):
        target = tmp_path / "out.json"
        run(capsys, "search", "seizure", "-a", "ols2", "--output", str(target))
        assert json.loads(target.read_text())["seizure"]["results_count"] == 5
        target = tmp_path / "out.csv"
        run(capsys, "search", "seizure", "-a", "ols2", "--output", str(target))
        assert target.read_text().startswith(",".join(SEARCH_COLUMNS))


class TestTables:
    def test_rich(self, http, capsys):
        code, out, _ = run(capsys, "search", "seizure", "-a", "ols2")
        assert code == cli.OK
        assert "Search Results" in out and "HP:0002349" in out

    def test_plain_without_rich(self, http, capsys, monkeypatch):
        monkeypatch.setattr(cli, "_have_rich", lambda: False)
        _, out, _ = run(capsys, "search", "seizure", "-a", "ols2")
        header, rule, first, *_ = out.splitlines()
        assert header.split() == list(cli.SEARCH_TABLE)
        assert set(rule) <= {"-", " "}
        assert first.startswith("seizure") and "HP:0002349" in first

    def test_rich_format_without_rich_is_an_error(self, http, monkeypatch):
        monkeypatch.setattr(cli, "_have_rich", lambda: False)
        with pytest.raises(SystemExit) as exit:
            cli.main(["search", "x", "-f", "rich"])
        assert exit.value.code == cli.USAGE

    def test_plain_table_truncates_and_flattens(self):
        out = io.StringIO()
        rows = [{"a": "x" * 100, "b": "two\nlines"}]
        write_plain_table(rows, ["a", "b"], out, max_width=10)
        line = out.getvalue().splitlines()[2]
        assert line == "xxxxxxxxx…  two lines"


class TestHierarchy:
    @pytest.fixture
    def routes(self, routes):
        return routes | {OLS2: "ols2_lookup_HP_0002197"}

    def test_descendants_csv_with_parent(self, http, capsys):
        code, out, _ = run(
            capsys, "descendants", "HPO:0002197", "--parent", "-f", "csv"
        )
        assert code == cli.OK
        parent, *rows = list(csv.DictReader(io.StringIO(out)))
        assert (parent["parent_code"], parent["descendant_code"]) == ("", "HP:0002197")
        assert rows and {r["parent_code"] for r in rows} == {"HP:0002197"}
        assert http.calls_to("/descendants")

    def test_children_free_text(self, http, capsys):
        http.routes[OLS2] = iter(["ols2_lookup_HP_0002197"] * 2)
        _, out, _ = run(
            capsys, "children", "generalized seizure", "-o", "HP", "-f", "json"
        )
        data = json.loads(out)
        assert data["direct"] is True
        assert data["parent"]["code"] == "HP:0002197"
        assert http.calls_to("/children")

    def test_free_text_without_ontology_exits_2(self, http):
        with pytest.raises(SystemExit) as exit:
            cli.main(["descendants", "seizure"])
        assert exit.value.code == cli.USAGE

    def test_not_found_exits_1(self, http, capsys):
        http.routes[OLS2] = EMPTY_OLS2
        code, _, err = run(capsys, "descendants", "HP:9999999")
        assert code == cli.NOT_FOUND
        assert "HP:9999999" in err
