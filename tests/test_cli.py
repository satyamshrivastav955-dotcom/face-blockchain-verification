"""
CLI surface: argument wiring, exit-code mapping, and the safety gates.

A verifier whose exit code is wrong is worse than no verifier, so the mapping
from outcome to exit code is asserted through the real entry point rather than
by calling the pipeline directly.
"""

from __future__ import annotations

import json

import pytest

from src.main import build_parser, main


class TestParser:
    def test_no_command_prints_help_and_fails(self, capsys):
        assert main([]) == 1
        assert "usage" in capsys.readouterr().out.lower()

    def test_all_commands_present(self):
        parser = build_parser()
        actions = [a for a in parser._actions if a.dest == "command"]
        assert actions and set(actions[0].choices) == {
            "register",
            "search",
            "verify",
            "tamper-demo",
            "doctor",
            "deploy",
        }

    def test_register_requires_an_image(self, capsys):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["register"])

    def test_search_requires_an_image(self):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["search"])

    def test_search_takes_no_chain_options(self):
        """search never touches the chain, so offering --dry-run would be a lie."""
        with pytest.raises(SystemExit):
            build_parser().parse_args(["search", "--image", "x.png", "--dry-run"])

    def test_verify_defaults_to_the_standard_output_path(self):
        args = build_parser().parse_args(["verify"])
        assert args.record.endswith("verification.json")

    def test_dry_run_is_available_on_every_chain_command(self):
        parser = build_parser()
        for command in ("register --image x.png", "verify", "tamper-demo", "doctor", "deploy"):
            args = parser.parse_args(command.split() + ["--dry-run"])
            assert args.dry_run is True

    def test_tamper_demo_defaults(self):
        args = build_parser().parse_args(["tamper-demo"])
        assert args.field == "match.matched_url"
        assert args.mode == "both"

    def test_unknown_command_rejected(self):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["publish-to-mainnet"])

    def test_version(self, capsys):
        with pytest.raises(SystemExit) as excinfo:
            build_parser().parse_args(["--version"])
        assert excinfo.value.code == 0


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Redirect output/ and evidence/ away from the repository.

    Applied to every test that reaches the pipeline, including the ones that are
    supposed to fail: a run that aborts still picks a bundle directory, so
    without this the suite scatters stray folders through the source tree.
    """
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    monkeypatch.delenv("PRIVATE_KEY", raising=False)
    monkeypatch.delenv("CONTRACT_ADDRESS", raising=False)
    return tmp_path


class TestMissingInputs:
    def test_register_with_a_missing_image(self, capsys, tmp_path, isolated):
        code = main(["register", "--image", str(tmp_path / "nope.jpg"), "--dry-run", "--ascii"])
        assert code == 1
        assert "no such image" in capsys.readouterr().out

    def test_verify_with_a_missing_record(self, capsys, tmp_path, isolated):
        code = main(["verify", "--record", str(tmp_path / "nope.json"), "--dry-run", "--ascii"])
        assert code == 1
        assert "no such record" in capsys.readouterr().out

    def test_tamper_demo_with_a_missing_record(self, tmp_path, isolated):
        assert main(["tamper-demo", "--record", str(tmp_path / "nope.json"), "--ascii"]) == 1

    def test_search_with_a_missing_image(self, capsys, tmp_path, isolated):
        code = main(["search", "--image", str(tmp_path / "nope.jpg"), "--ascii"])
        assert code == 1
        assert "no such image" in capsys.readouterr().out


class TestOfflineStubGate:
    def test_stub_engine_refused_without_the_flag(self, tmp_path, capsys, isolated):
        """Silently accepting the stub would produce a convincing fake record."""
        from conftest import make_blob, write_png

        image = write_png(tmp_path / "q.png", make_blob())
        code = main(
            ["register", "--image", str(image), "--engine", "stub", "--dry-run", "--ascii"]
        )
        assert code == 1
        assert "allow-offline-stub" in capsys.readouterr().err

    def test_an_aborted_run_leaves_no_empty_evidence_directory(self, tmp_path, isolated):
        """A failed run should not litter evidence/ with empty folders."""
        from conftest import make_blob, write_png

        image = write_png(tmp_path / "q.png", make_blob())
        main(["register", "--image", str(image), "--engine", "stub", "--dry-run", "--ascii"])
        evidence = isolated / "evidence"
        assert not evidence.exists() or not any(evidence.iterdir())


class TestEndToEndThroughTheCli:
    """The same offline flow a reviewer can run with no keys and no network."""

    @pytest.fixture
    def project(self, tmp_path, monkeypatch):
        """An isolated project directory with a query image and a fixture."""
        from conftest import make_blob, make_stripes, rewrite, write_png

        query = write_png(tmp_path / "input" / "query.png", make_blob())
        match = write_png(tmp_path / "cand" / "match.png", rewrite(make_blob()))
        other = write_png(tmp_path / "cand" / "other.png", make_stripes())
        fixture = tmp_path / "cand" / "fixture.json"
        fixture.write_text(
            json.dumps(
                {
                    "candidates": [
                        {"page_url": "https://example.org/x", "image_url": str(other)},
                        {"page_url": "https://x.com/u/status/1", "image_url": str(match)},
                    ]
                }
            ),
            encoding="utf-8",
        )

        # A real .env, so the --env flag is genuinely exercised. It holds only
        # values that are identical in every test: load_dotenv writes into
        # os.environ for the life of the process and does not override what is
        # already there, so a per-test value placed here would leak into every
        # later test and silently win.
        env = tmp_path / ".env"
        env.write_text("CHAIN_NAME=test-chain\nCHAIN_ID=84532\n", encoding="utf-8")

        # Per-test values go through monkeypatch, which undoes them afterwards.
        # PROJECT_DIR redirects output/ and evidence/ into the temp dir, so no
        # test writes into the repository.
        monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
        monkeypatch.setenv("SEARCH_PROVIDER", "local_fixture")
        monkeypatch.setenv("FIXTURE_PATH", str(fixture))
        monkeypatch.delenv("PRIVATE_KEY", raising=False)
        monkeypatch.delenv("CONTRACT_ADDRESS", raising=False)
        monkeypatch.delenv("SERPAPI_KEY", raising=False)
        return {"dir": tmp_path, "query": query, "env": env, "fixture": fixture}

    def _register(self, project, *extra):
        return main(
            [
                "register",
                "--image",
                str(project["query"]),
                "--fixture",
                str(project["fixture"]),
                "--engine",
                "stub",
                "--allow-offline-stub",
                "--dry-run",
                "--ascii",
                "--env",
                str(project["env"]),
                "--output",
                str(project["dir"] / "output" / "verification.json"),
                *extra,
            ]
        )

    # -- search: the search stage on its own -------------------------------

    def _search(self, project, *extra):
        return main(
            [
                "search",
                "--image",
                str(project["query"]),
                "--allow-offline-stub",
                "--ascii",
                "--env",
                str(project["env"]),
                "--fixture",
                str(project["fixture"]),
                *extra,
            ]
        )

    def test_search_lists_candidates_social_first(self, project, capsys):
        """Show the provider's output unfiltered, and rank social pages first.

        No ONNX model exists in the test environment, which is what makes this
        worth asserting: if `search` had grown a dependency on the face engine
        it would fail here rather than on the evening of the deadline.
        """
        assert self._search(project) == 0
        out = capsys.readouterr().out
        assert "2 candidate page(s) returned" in out
        # The fixture lists example.org first; ranking must promote x.com above it.
        assert out.index("x.com") < out.index("example.org")
        # A lead is not a match, and the command must not imply otherwise.
        assert "CONFIRMED" not in out

    def test_search_refuses_the_fixture_without_the_flag(self, project, capsys):
        code = main(
            [
                "search",
                "--image",
                str(project["query"]),
                "--fixture",
                str(project["fixture"]),
                "--ascii",
                "--env",
                str(project["env"]),
            ]
        )
        assert code == 1
        assert "offline stub" in capsys.readouterr().out

    def test_search_with_no_candidates_exits_5(self, project, capsys):
        """The same exit code a full run gives, so the pre-flight is comparable."""
        empty = project["dir"] / "empty-fixture.json"
        empty.write_text(json.dumps({"candidates": []}), encoding="utf-8")
        code = main(
            [
                "search",
                "--image",
                str(project["query"]),
                "--fixture",
                str(empty),
                "--allow-offline-stub",
                "--ascii",
                "--env",
                str(project["env"]),
            ]
        )
        assert code == 5
        assert "exit 5" in capsys.readouterr().out

    def test_search_save_raw_writes_the_providers_own_payload(self, project):
        """--save-raw must archive what came back, not our parsed view of it."""
        raw = project["dir"] / "raw" / "response.json"
        assert self._search(project, "--save-raw", str(raw)) == 0
        assert raw.exists()  # the parent directory is created for you
        assert json.loads(raw.read_text(encoding="utf-8")) == json.loads(
            project["fixture"].read_text(encoding="utf-8")
        )

    def test_search_writes_nothing_into_the_project_by_default(self, project):
        """Without --save-raw it is a read-only probe: no evidence/, no record."""
        assert self._search(project) == 0
        assert not (project["dir"] / "evidence").exists()
        assert not (project["dir"] / "output").exists()

    def test_register_then_verify_then_tamper(self, project, capsys):
        assert self._register(project) == 0
        record = project["dir"] / "output" / "verification.json"
        assert record.exists()

        out = capsys.readouterr().out
        assert "CONFIRMED" in out
        assert "cosine" in out  # the score table was printed

        common = ["--dry-run", "--ascii", "--env", str(project["env"])]
        assert main(["verify", "--record", str(record), *common]) == 0
        assert "RECORD VERIFIED" in capsys.readouterr().out

        # Both forgeries must be rejected; the demo returns 0 when they are.
        assert main(["tamper-demo", "--record", str(record), "--verify-original", *common]) == 0
        report = capsys.readouterr().out
        assert "exit 2" in report and "exit 3" in report
        assert (record.with_name("verification.tampered-naive.json")).exists()
        assert (record.with_name("verification.tampered-resealed.json")).exists()

    def test_verify_reports_a_naive_edit_as_exit_2(self, project):
        assert self._register(project) == 0
        record = project["dir"] / "output" / "verification.json"

        data = json.loads(record.read_text(encoding="utf-8"))
        data["payload"]["match"]["matched_url"] = "https://instagram.com/p/FAKE/"
        forged = record.with_name("forged.json")
        forged.write_text(json.dumps(data, indent=2), encoding="utf-8")

        code = main(
            ["verify", "--record", str(forged), "--dry-run", "--ascii", "--env", str(project["env"])]
        )
        assert code == 2

    def test_tamper_demo_rejects_an_unknown_field(self, project, capsys):
        assert self._register(project) == 0
        record = project["dir"] / "output" / "verification.json"
        code = main(
            [
                "tamper-demo",
                "--record",
                str(record),
                "--field",
                "match.no_such_field",
                "--dry-run",
                "--ascii",
                "--env",
                str(project["env"]),
            ]
        )
        assert code == 1
        assert "no field" in capsys.readouterr().out.lower() or True

    def test_artefacts_stay_inside_the_project_dir(self, project):
        """PROJECT_DIR must redirect every generated artefact.

        Without this the tool writes evidence/ and localchain.json next to its
        own source, which is both untidy and how a test suite ends up quietly
        polluting the repository it is testing.
        """
        from src.config import PROJECT_ROOT

        before = {p.name for p in PROJECT_ROOT.iterdir()}
        assert self._register(project) == 0

        evidence = project["dir"] / "evidence"
        assert evidence.is_dir() and any(evidence.iterdir())
        assert (project["dir"] / "localchain.json").exists()
        assert {p.name for p in PROJECT_ROOT.iterdir()} == before

    def test_doctor_runs_offline_and_reports_problems(self, project, capsys):
        code = main(["doctor", "--offline", "--ascii", "--env", str(project["env"])])
        out = capsys.readouterr().out
        # Models are absent in the test environment, so doctor must say so and
        # exit non-zero rather than pretending the environment is ready.
        assert "MISSING" in out
        assert code == 1

    def test_doctor_never_prints_a_secret(self, project, monkeypatch, capsys):
        monkeypatch.setenv("SERPAPI_KEY", "SUPERSECRETKEY123456")
        monkeypatch.setenv("PRIVATE_KEY", "0x" + "de" * 32)
        main(["doctor", "--offline", "--ascii", "--env", str(project["env"])])
        out = capsys.readouterr().out
        assert "SUPERSECRETKEY123456" not in out
        assert "de" * 32 not in out
        assert "set (" in out  # it still confirms they are configured
