"""
End-to-end pipeline, entirely offline.

Runs register -> verify -> tamper for real, using the three offline
substitutes (stub engine, fixture provider, simulated chain). Nothing here
touches the network, so this is the test that can actually be run on any
machine, in CI, or five minutes before a deadline.

What it proves:

* a confirmed match produces a sealed, anchored record that verifies (exit 0);
* an *unconfirmed* run refuses to write anything to the chain (exit 5), which
  is the property that distinguishes an honest pipeline from a hardcoded one;
* a naively edited record fails locally (exit 2);
* a re-sealed edited record passes every local check and is caught only by the
  chain (exit 3);
* the evidence bundle contains the raw provider response and the full score
  table, including rejections.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.pipeline import EXIT_ERROR, EXIT_NO_MATCH, EXIT_OK, run_register, run_verify
from src.record import Status, check_local_integrity, load_record, mutate_payload, seal, save_record
from src.ui import Console

from conftest import make_blob, make_stripes, rewrite, write_png


def register(settings, scene, **kwargs) -> int:
    settings.fixture_path = str(scene["fixture"])
    return run_register(
        settings,
        scene["query"],
        provider_name="local_fixture",
        engine_name="stub",
        dry_run=True,
        allow_offline_stub=True,
        console=Console(force_ascii=True),
        **kwargs,
    )


@pytest.fixture
def registered(settings, scene):
    assert register(settings, scene) == EXIT_OK
    return settings.output_dir / "verification.json"


class TestRegister:
    def test_exit_code_and_record(self, registered):
        assert registered.exists()
        record = load_record(registered)
        assert check_local_integrity(record).ok

    def test_the_social_post_was_chosen(self, registered):
        match = load_record(registered)["payload"]["match"]
        assert match["matched_url"] == "https://x.com/testuser/status/1234567890"
        assert match["matched_domain"] == "x.com"
        assert match["is_social_media"] is True

    def test_scores_are_recorded_as_strings(self, registered):
        match = load_record(registered)["payload"]["match"]
        assert isinstance(match["face_similarity"], str)
        assert float(match["face_similarity"]) >= float(match["face_cosine_threshold"])
        assert isinstance(match["phash_distance"], int)

    def test_the_offline_stub_is_declared_inside_the_hash(self, registered):
        """A record made without a real search must say so, permanently."""
        payload = load_record(registered)["payload"]
        assert payload["search"]["offline_stub"] is True
        assert payload["search"]["provider"] == "local_fixture"
        assert payload["face"]["engine"] == "stub-test-only"

    def test_no_embedding_is_published(self, registered):
        """Only a fingerprint of the embedding may leave the machine.

        Asserted structurally rather than by substring search: a naive
        ``"embedding" not in json.dumps(...)`` also matches incidental text such
        as a file path, so it can pass or fail for reasons unrelated to privacy.
        """
        payload = load_record(registered)["payload"]
        assert payload["face"]["embedding_on_chain"] is False
        assert len(payload["face"]["embedding_sha256"]) == 64
        assert "embedding" not in payload["match"]
        assert "embedding" not in payload["face"]["primary"]
        assert _numeric_vectors(payload) == [], "a raw vector reached the record"

    def test_the_claim_is_provenance_not_identity(self, registered):
        claim = load_record(registered)["payload"]["match"]["claim"]
        assert "provenance" in claim and "not" in claim

    def test_anchor_is_present_and_marked_simulated(self, registered):
        anchor = load_record(registered)["anchor"]
        assert anchor["simulated"] is True
        assert anchor["tx_hash"].startswith("0x")
        assert anchor["block_number"] >= 1

    def test_rejected_candidate_is_still_in_the_evidence(self, settings, registered):
        candidates = _bundle_file(settings, "candidates.json")
        data = json.loads(candidates.read_text(encoding="utf-8"))
        assert len(data) == 2
        statuses = {row["domain"]: row["status"] for row in data}
        assert statuses["x.com"].startswith("confirmed")
        assert statuses["example.org"].startswith("rejected")

    def test_raw_search_response_is_archived_and_hashed(self, settings, registered):
        raw = _bundle_file(settings, "search_response.raw.json")
        from src.canonical import sha256_bytes

        declared = load_record(registered)["payload"]["search"]["raw_response_sha256"]
        assert sha256_bytes(raw.read_bytes()) == declared

    def test_bundle_manifest_covers_every_artefact(self, settings, registered):
        manifest = json.loads(_bundle_file(settings, "manifest.json").read_text(encoding="utf-8"))
        names = {entry["file"] for entry in manifest["files"]}
        assert {"query_face.png", "comparison.png", "candidates.json", "verification.json"} <= names
        assert all(len(entry["sha256"]) == 64 for entry in manifest["files"])

    def test_custom_output_path(self, settings, scene, tmp_path):
        out = tmp_path / "custom" / "record.json"
        assert register(settings, scene, output=out) == EXIT_OK
        assert out.exists()


class TestNegativeCase:
    def test_no_confirmed_match_refuses_to_anchor(self, settings, tmp_path):
        """The most important negative test in the suite.

        A pipeline that always produces a match is indistinguishable from one
        that fabricates them. This asserts the pipeline can say "no".
        """
        query = write_png(tmp_path / "input" / "q.png", make_blob())
        decoy = write_png(tmp_path / "cand" / "decoy.png", make_stripes())
        fixture = tmp_path / "cand" / "fixture.json"
        fixture.write_text(
            json.dumps(
                {"candidates": [{"page_url": "https://x.com/nobody/status/1", "image_url": str(decoy)}]}
            ),
            encoding="utf-8",
        )

        code = register(settings, {"query": query, "fixture": fixture})
        assert code == EXIT_NO_MATCH
        assert not (settings.output_dir / "verification.json").exists()

    def test_a_no_match_report_is_still_written(self, settings, tmp_path):
        query = write_png(tmp_path / "input" / "q.png", make_blob())
        decoy = write_png(tmp_path / "cand" / "decoy.png", make_stripes())
        fixture = tmp_path / "cand" / "fixture.json"
        fixture.write_text(
            json.dumps(
                {"candidates": [{"page_url": "https://x.com/nobody/status/1", "image_url": str(decoy)}]}
            ),
            encoding="utf-8",
        )
        register(settings, {"query": query, "fixture": fixture})
        report = json.loads(_bundle_file(settings, "no_match_report.json").read_text("utf-8"))
        assert report["outcome"] == "no_confirmed_match"
        assert report["candidates_considered"] == 1

    def test_empty_candidate_list(self, settings, tmp_path):
        query = write_png(tmp_path / "input" / "q.png", make_blob())
        fixture = tmp_path / "empty.json"
        fixture.write_text(json.dumps({"candidates": []}), encoding="utf-8")
        assert register(settings, {"query": query, "fixture": fixture}) == EXIT_NO_MATCH


class TestGuards:
    def test_stub_engine_refused_without_the_flag(self, settings, scene):
        """Silently falling back to the stub would produce a convincing fake."""
        from src.config import ConfigError

        settings.fixture_path = str(scene["fixture"])
        with pytest.raises(ConfigError) as excinfo:
            run_register(
                settings,
                scene["query"],
                provider_name="local_fixture",
                engine_name="stub",
                dry_run=True,
                allow_offline_stub=False,
                console=Console(force_ascii=True),
            )
        assert "allow-offline-stub" in str(excinfo.value)
        assert not (settings.output_dir / "verification.json").exists()

    def test_fixture_provider_refused_without_the_flag(self, settings, scene, monkeypatch):
        """The offline provider must not be usable by accident either.

        A real engine is substituted in directly so this reaches the *provider*
        guard instead of tripping the engine guard first: both sit behind the
        same flag, so the two paths cannot be exercised in one call.
        """
        import src.pipeline as pipeline
        from src.faces import StubFaceEngine

        monkeypatch.setattr(pipeline, "build_engine", lambda *a, **k: StubFaceEngine())
        settings.fixture_path = str(scene["fixture"])
        code = run_register(
            settings,
            scene["query"],
            provider_name="local_fixture",
            engine_name="opencv",
            dry_run=True,
            allow_offline_stub=False,
            console=Console(force_ascii=True),
        )
        assert code == EXIT_ERROR
        assert not (settings.output_dir / "verification.json").exists()

    def test_missing_models_raise_a_clear_error(self, settings, scene):
        # The stub treats any non-empty image as a face, so use the real engine
        # with no weights on disk to hit the model-guard path deterministically.
        from src.faces import ModelMissingError

        settings.fixture_path = str(scene["fixture"])
        with pytest.raises(ModelMissingError) as excinfo:
            run_register(
                settings,
                scene["query"],
                provider_name="local_fixture",
                engine_name="opencv",
                dry_run=True,
                allow_offline_stub=True,
                console=Console(force_ascii=True),
            )
        assert "fetch_models" in str(excinfo.value)


class TestVerify:
    def test_genuine_record_verifies(self, settings, registered):
        code = run_verify(settings, registered, dry_run=True, console=Console(force_ascii=True))
        assert code == Status.OK.exit_code == 0

    def test_image_binding_passes_for_the_right_file(self, settings, scene, registered):
        code = run_verify(
            settings,
            registered,
            dry_run=True,
            image_path=scene["query"],
            console=Console(force_ascii=True),
        )
        assert code == 0

    def test_image_binding_fails_for_a_different_file(self, settings, scene, registered):
        code = run_verify(
            settings,
            registered,
            dry_run=True,
            image_path=scene["other"],
            console=Console(force_ascii=True),
        )
        assert code == Status.LOCAL_HASH_MISMATCH.exit_code

    def test_simulated_records_are_rechecked_against_the_simulation(self, settings, registered):
        """Passing dry_run=False on a simulated record must not silently pass.

        It is re-routed to the simulated chain (with a warning) rather than
        being reported as unanchored, which would be a misleading verdict.
        """
        code = run_verify(settings, registered, dry_run=False, console=Console(force_ascii=True))
        assert code == 0


class TestTamperDetection:
    def test_naive_edit_fails_locally(self, settings, registered, tmp_path):
        record = load_record(registered)
        mutate_payload(record, "match.matched_url", "https://instagram.com/p/ATTACKER/")
        forged = tmp_path / "naive.json"
        forged.write_text(json.dumps(record, indent=2), encoding="utf-8")

        code = run_verify(settings, forged, dry_run=True, console=Console(force_ascii=True))
        assert code == Status.LOCAL_HASH_MISMATCH.exit_code == 2

    def test_resealed_edit_is_caught_only_by_the_chain(self, settings, registered, tmp_path):
        record = load_record(registered)
        anchor = record["anchor"]
        mutate_payload(record, "match.matched_url", "https://instagram.com/p/ATTACKER/")
        forged_record = seal(record["payload"])
        forged_record["anchor"] = anchor  # keeps the original, real transaction

        # Internally flawless: no local check can fault it.
        assert check_local_integrity(forged_record).ok

        forged = save_record(forged_record, tmp_path / "resealed.json")
        code = run_verify(settings, forged, dry_run=True, console=Console(force_ascii=True))
        assert code == Status.NOT_ANCHORED.exit_code == 3

    @pytest.mark.parametrize(
        "field,value",
        [
            ("match.face_similarity", "0.9999"),
            ("match.matched_image_sha256", "0" * 64),
            ("source_image.sha256", "1" * 64),
            ("face.embedding_sha256", "2" * 64),
            ("search.candidates_returned", 999),
        ],
    )
    def test_every_meaningful_field_is_protected(self, settings, registered, tmp_path, field, value):
        record = load_record(registered)
        mutate_payload(record, field, value)
        forged = tmp_path / "f.json"
        forged.write_text(json.dumps(record, indent=2), encoding="utf-8")
        assert run_verify(settings, forged, dry_run=True, console=Console(force_ascii=True)) == 2

    def test_editing_anchor_metadata_does_not_invalidate_the_record(
        self, settings, registered, tmp_path
    ):
        """The anchor block is metadata, not part of the sealed claim.

        Editing it cannot change the verdict, because the verdict is decided by
        the payload hash and by what the chain says about it - not by what the
        file claims about itself. This is why verify re-derives the hash and
        re-queries the chain instead of trusting anchor.tx_hash.
        """
        record = load_record(registered)
        record["anchor"]["explorer_url"] = "https://sepolia.basescan.org/tx/0xdeadbeef"
        record["anchor"]["tx_hash"] = "0x" + "ff" * 32
        forged = save_record(record, tmp_path / "anchor_edit.json")
        assert run_verify(settings, forged, dry_run=True, console=Console(force_ascii=True)) == 0


class TestUrlCommitment:
    def test_the_chain_holds_the_matched_url(self, settings, registered):
        """The anchored URL is checked against the record, not taken on trust."""
        from src.chain import build_chain_client

        record = load_record(registered)
        client = build_chain_client(settings, dry_run=True, require_signer=False)
        data_hash = record["integrity"]["verification_hash"]
        assert client.matches_url(data_hash, record["payload"]["match"]["matched_url"])
        assert not client.matches_url(data_hash, "https://instagram.com/p/ATTACKER/")


def _bundle_file(settings, name: str) -> Path:
    """Locate a file inside the single evidence bundle produced by a run."""
    runs = sorted(p for p in settings.evidence_dir.iterdir() if p.is_dir())
    assert runs, "no evidence bundle was written"
    path = runs[-1] / name
    assert path.exists(), f"{name} missing from {runs[-1]}"
    return path


def _numeric_vectors(node, path: str = "", found: list | None = None) -> list:
    """Every list of more than eight numbers found anywhere in the payload.

    A 128-d face embedding cannot hide from this, whatever the key is called.
    """
    found = [] if found is None else found
    if isinstance(node, dict):
        for key, value in node.items():
            _numeric_vectors(value, f"{path}.{key}" if path else key, found)
    elif isinstance(node, list):
        numbers = [v for v in node if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if len(numbers) > 8:
            found.append(path)
        else:
            for index, value in enumerate(node):
                _numeric_vectors(value, f"{path}[{index}]", found)
    return found
