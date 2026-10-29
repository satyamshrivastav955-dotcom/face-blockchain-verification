"""
Pipeline orchestration for ``register`` and ``verify``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .blockchain.client import ChainError, EvmChainClient, build_chain_client, url_commitment
from .config import SOCIAL_DOMAINS, ConfigError, Settings
from .evidence.bundle import EvidenceBundle, new_run_id, verify_bundle
from .evidence.hashing import canonicalize, fmt_score, sha256_bytes, sha256_file
from .evidence.record import (
    Status,
    attach_anchor,
    build_payload,
    check_local_integrity,
    load_record,
    save_record,
    seal,
)
from .privacy import ConsentError, require_consent
from .publish import PublishError, publish_image
from .search import SearchError, build_provider, is_social, rank_candidates
from .ui import Console
from .verification.candidate_matcher import (
    ConfirmationStatus,
    claim_for,
    confirm_candidates,
    limitations_for,
    score_table,
    select_best,
)
from .vision.face_detector import (
    OpenCVFaceEngine,
    StubFaceEngine,
    embedding_fingerprint,
)
from .vision.preprocess import (
    decode_image_safely,
    image_info,
    load_image,
    phash,
    phash_hex,
    side_by_side,
)

__all__ = [
    "EXIT_OK",
    "EXIT_ERROR",
    "EXIT_NO_MATCH",
    "EXIT_INCONCLUSIVE",
    "build_engine",
    "run_register",
    "run_verify",
]

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NO_MATCH = 5
EXIT_INCONCLUSIVE = Status.INCONCLUSIVE.exit_code  # 6

_VERDICT_NAMES = {
    Status.OK: "verified",
    Status.LOCAL_HASH_MISMATCH: "local_hash_mismatch",
    Status.NOT_ANCHORED: "not_anchored",
    Status.ANCHOR_MISMATCH: "anchor_mismatch",
    Status.INCONCLUSIVE: "inconclusive",
}


def build_engine(name: str, settings: Settings, *, allow_stub: bool = False):
    """Instantiate the face engine.

    The stub engine is gated behind an explicit flag: it is not a face detector,
    and silently falling back to it would produce a record that looks real.
    """
    key = (name or "opencv").lower()
    if key in ("opencv", "yunet", "sface", "default"):
        return OpenCVFaceEngine(settings.models_dir)
    if key == "stub":
        if not allow_stub:
            raise ConfigError(
                "the stub face engine is for offline tests only. Pass "
                "--allow-offline-stub if you really mean to use it."
            )
        return StubFaceEngine()
    raise ConfigError(f"unknown face engine {name!r} (expected 'opencv' or 'stub')")


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------


def run_register(
    settings: Settings,
    image_path: str | Path,
    *,
    provider_name: str = "",
    engine_name: str = "opencv",
    image_url: str = "",
    dry_run: bool = False,
    max_candidates: int | None = None,
    stop_early: bool = False,
    allow_offline_stub: bool = False,
    consent_external_search: bool = False,
    consent_public_upload: bool = False,
    require_face_match: bool = False,
    minimal_evidence: bool = False,
    output: str | Path | None = None,
    console: Console | None = None,
) -> int:
    ui = console or Console()
    path = Path(image_path)
    limit = max_candidates or settings.max_candidates
    settings.validate()

    ui.header("Image provenance verification  -  REGISTER")

    # -- stage 1: the input image -----------------------------------------
    ui.step("Reading input image")
    image = load_image(path)
    info = image_info(image)
    image_sha256 = sha256_file(path)
    query_phash = phash(image)
    ui.ok(f"{path.name}  {info['width']}x{info['height']}  {path.stat().st_size:,} bytes")
    ui.info(f"sha256  {image_sha256}")
    ui.info(f"pHash   {query_phash:016x}")

    run_id = new_run_id(image_sha256)
    bundle = EvidenceBundle(settings.evidence_dir, run_id)

    # -- stage 2: face detection and embedding (local) ---------------------
    ui.step("Detecting and encoding face (local)")
    engine = build_engine(engine_name, settings, allow_stub=allow_offline_stub)
    stub_engine = isinstance(engine, StubFaceEngine)
    if stub_engine:
        ui.banner(
            [
                "WARNING: using the STUB face engine.",
                "This is a test harness, not a face detector.",
                "Any record produced is NOT a real verification.",
            ]
        )

    faces = engine.analyze(image)
    embeddable = [f for f in faces if f.embedding is not None]
    if not embeddable:
        ui.fail("no face detected in the input image - nothing to verify")
        ui.info("try a clearer, front-facing photo where the face is at least 60px wide")
        return EXIT_ERROR

    primary = embeddable[0]
    ui.ok(f"{len(faces)} face(s) detected, {len(embeddable)} encodable")
    if len(embeddable) > 1:
        ui.warn(
            "several faces found: the LARGEST one is used as the query face (crop the photo if that is not the subject)"
        )
    x, y, w, h = primary.bbox
    ui.info(f"primary face bbox x={x} y={y} w={w} h={h}  score={fmt_score(primary.det_score)}")
    ui.info(f"embedding: {primary.embedding.size}-d via {engine.name}")
    ui.info(f"embedding commitment sha256 {embedding_fingerprint(primary.embedding)[:32]}...")
    ui.info("(the embedding itself is never saved, published or written on-chain)")
    if not minimal_evidence:
        bundle.write_image("query_face.png", primary.aligned)

    # -- stage 3: reverse image search (third party unless offline) --------
    ui.step("Reverse image search")
    provider = build_provider(provider_name or settings.search_provider, settings)

    if provider.is_offline_stub:
        if not allow_offline_stub:
            ui.fail(f"provider '{provider.name}' is an offline stub and cannot produce a genuine match")
            ui.info("pass --allow-offline-stub to use it for plumbing tests")
            return EXIT_ERROR
        ui.banner(
            [
                "WARNING: offline fixture provider in use.",
                "No real reverse-image search was performed.",
                "Records produced are labelled test-only.",
            ]
        )
    else:
        try:
            disclosures = require_consent(
                provider_name=provider.name,
                is_offline_stub=False,
                needs_public_url=provider.needs_public_url,
                publish_provider=settings.publish_provider,
                have_image_url=bool(image_url),
                consent_external_search=consent_external_search,
                consent_public_upload=consent_public_upload,
            )
        except ConsentError as exc:
            first, *rest = str(exc).splitlines()
            ui.fail(first)
            for line in rest:
                ui.info(line)
            return EXIT_ERROR
        ui.warn("EXTERNAL PROCESSING - consent given for:")
        for item in disclosures:
            ui.info(f"{item.service}: {item.what_is_sent}")

    query_url = image_url
    if provider.needs_public_url and not query_url:
        ui.info(f"{provider.name} requires a public image URL; uploading via {settings.publish_provider}")
        try:
            query_url = publish_image(path, settings.publish_provider, imgbb_api_key=settings.imgbb_api_key)
        except PublishError as exc:
            ui.fail(f"could not publish the query image: {exc}")
            return EXIT_ERROR
        ui.ok(f"query image published at {query_url}")

    ui.info(f"provider: {provider.name}  endpoint: {provider.describe()}")
    try:
        result = provider.search(path, image_url=query_url, max_results=limit)
    except SearchError as exc:
        # A provider failure is NOT a negative result.
        ui.fail(f"the search could not be completed: {exc}")
        ui.info("this is a technical failure, not evidence that the image has no matches")
        return EXIT_ERROR

    raw_bytes = json.dumps(result.raw_response, indent=2, sort_keys=True, ensure_ascii=False, default=str).encode(
        "utf-8"
    )
    bundle.write_bytes("search_response.raw.json", raw_bytes)
    raw_sha256 = sha256_bytes(raw_bytes)

    ui.ok(f"{len(result.candidates)} candidate page(s) returned")
    ui.info(f"raw response archived, sha256 {raw_sha256[:32]}...")
    if not result.candidates:
        ui.fail("the search returned no candidates at all")
        ui.info("this image may not be indexed anywhere; try a widely published photo")
        bundle.finalize()
        return EXIT_NO_MATCH

    ranked = rank_candidates(result.candidates, SOCIAL_DOMAINS)
    social_count = sum(1 for c in ranked if is_social(c.page_url, SOCIAL_DOMAINS))
    ui.info(f"{social_count} of them are on social-media domains (checked first)")

    # -- stage 4: independent confirmation (local) -------------------------
    ui.step("Confirming candidates locally (re-detect, re-embed, re-hash)")
    ui.info("a search hit is only a lead; each one is verified independently below")
    confirmations = confirm_candidates(
        query_embedding=primary.embedding,
        query_phash=query_phash,
        candidates=ranked,
        engine=engine,
        cosine_threshold=settings.face_cosine_threshold,
        phash_max_distance=settings.phash_max_distance,
        social_domains=SOCIAL_DOMAINS,
        max_candidates=limit,
        stop_early=stop_early,
        allow_local_files=bool(provider.is_offline_stub),
        progress=ui.out,
    )

    ui.out()
    ui.out(score_table(confirmations))

    candidate_json = [c.to_json() for c in confirmations]
    candidates_canonical = canonicalize(candidate_json)
    bundle.write_bytes("candidates.canonical.json", candidates_canonical)
    bundle.write_json("candidates.json", candidate_json)
    candidates_sha256 = sha256_bytes(candidates_canonical)

    allowed = (ConfirmationStatus.FACE_MATCH,) if require_face_match else ConfirmationStatus.CONFIRMED
    best = select_best(confirmations, allowed=allowed)
    failed = [c for c in confirmations if c.failed]
    measured = len(confirmations) - len(failed)

    if best is None:
        ui.out()
        if measured == 0:
            ui.fail("no candidate could be evaluated - this is NOT a negative result")
            ui.info(
                f"{len(failed)} candidate(s) were skipped (no image URL, download "
                "failure or blocked URL); see the table above"
            )
            bundle.write_json(
                "no_match_report.json",
                {
                    "source_image_sha256": image_sha256,
                    "searched_at": result.searched_at,
                    "provider": result.provider,
                    "candidates_considered": len(confirmations),
                    "candidates_sha256": candidates_sha256,
                    "outcome": "inconclusive_no_candidate_evaluated",
                },
            )
            bundle.finalize()
            ui.info(f"evidence written to {bundle.dir}")
            return EXIT_ERROR

        ui.fail("no candidate passed independent confirmation")
        ui.info(
            f"best face similarity was "
            f"{fmt_score(max((c.face_similarity for c in confirmations), default=0.0))}, "
            f"threshold is {fmt_score(settings.face_cosine_threshold)}"
        )
        if require_face_match and any(c.status == ConfirmationStatus.IMAGE_DERIVATIVE for c in confirmations):
            ui.info("an image-derivative candidate exists but --require-face-match excludes it")
        if failed:
            ui.info(f"{len(failed)} candidate(s) could not be checked at all")
        ui.info("refusing to write an unconfirmed claim to the blockchain")
        bundle.write_json(
            "no_match_report.json",
            {
                "source_image_sha256": image_sha256,
                "searched_at": result.searched_at,
                "provider": result.provider,
                "candidates_considered": len(confirmations),
                "candidates_unmeasured": len(failed),
                "candidates_sha256": candidates_sha256,
                "outcome": "no_confirmed_match",
            },
        )
        bundle.finalize()
        ui.info(f"evidence written to {bundle.dir}")
        return EXIT_NO_MATCH

    is_face = best.status == ConfirmationStatus.FACE_MATCH
    ui.out()
    if is_face:
        ui.ok(f"FACE MATCH on {best.candidate.domain}")
    else:
        ui.ok(f"IMAGE-DERIVATIVE match on {best.candidate.domain}")
        ui.warn("perceptual-hash similarity only: the face test did NOT confirm a match")
        ui.info("this is registered as an image-similarity claim, not a face match")
    ui.field("matched post", best.candidate.page_url)
    ui.field(
        "face similarity",
        f"{fmt_score(best.face_similarity)} (threshold {fmt_score(settings.face_cosine_threshold)})"
        f" - {'PASSED' if best.face_check_passed else 'not passed'}",
    )
    ui.field(
        "pHash distance",
        f"{best.phash_distance}/64 (max {settings.phash_max_distance})"
        f" - {'PASSED' if best.derivative_check_passed else 'not passed'}",
    )

    if not minimal_evidence:
        bundle.write_image("matched_face.png", best.candidate_face.aligned if best.candidate_face else None)
        if best.candidate_image_bytes:
            bundle.write_bytes("matched_image.original", best.candidate_image_bytes)
        comparison = side_by_side(
            primary.aligned,
            best.candidate_face.aligned if best.candidate_face else None,
            similarity=fmt_score(best.face_similarity),
            threshold=fmt_score(settings.face_cosine_threshold),
            phash_distance=int(best.phash_distance or 0),
            matched_url=best.candidate.page_url,
            accepted=is_face,
            verdict=("FACE MATCH" if is_face else "IMAGE DERIVATIVE (pHash only; face test not passed)"),
        )
        bundle.write_image("comparison.png", comparison)
    else:
        ui.info("--minimal-evidence: face crops, matched image bytes and comparison image not saved")

    # -- stage 5: build and seal the record --------------------------------
    ui.step("Building the verification record")
    candidate_image = None
    if best.candidate_image_bytes:
        try:
            candidate_image = decode_image_safely(best.candidate_image_bytes)
        except Exception:  # noqa: BLE001 - the digest is still recorded
            candidate_image = None

    claim = claim_for(best.status)
    if stub_engine:
        claim = "TEST ONLY - stub engine, no real face analysis was performed: " + claim

    payload = build_payload(
        source_image={
            "filename": path.name,
            "sha256": image_sha256,
            "bytes": int(path.stat().st_size),
            "width": info["width"],
            "height": info["height"],
            "phash": f"{query_phash:016x}",
        },
        face={
            "engine": engine.name,
            "models": engine.model_versions(),
            "face_count": len(faces),
            "encodable_face_count": len(embeddable),
            "primary": primary.to_json(),
            "primary_det_score": fmt_score(primary.det_score),
            "embedding_dim": int(primary.embedding.size),
            # A SHA-256 commitment to the embedding. It is NOT anonymisation:
            # it reveals nothing useful on its own, but whoever holds the same
            # embedding can confirm it, so treat it as personal data.
            "embedding_commitment_sha256": embedding_fingerprint(primary.embedding),
            "embedding_on_chain": False,
        },
        search={
            "provider": result.provider,
            "endpoint": result.endpoint,
            "searched_at": result.searched_at,
            "query_image_url": result.query_image_url,
            "raw_response_sha256": raw_sha256,
            "candidates_returned": len(result.candidates),
            "candidates_confirmed": len(confirmations),
            "candidates_unmeasured": len(failed),
            "candidates_sha256": candidates_sha256,
            "offline_stub": bool(provider.is_offline_stub),
        },
        match={
            "evidence_type": best.evidence_type,
            "decision_rule": best.status,
            "face_check_passed": bool(best.face_check_passed),
            "image_derivative_check_passed": bool(best.derivative_check_passed),
            "matched_url": best.candidate.page_url,
            "matched_url_commitment": url_commitment(best.candidate.page_url),
            "matched_domain": best.candidate.domain,
            "matched_image_url": best.candidate.best_image_url(),
            "matched_image_sha256": best.candidate_image_sha256,
            "matched_image_phash": (phash_hex(candidate_image) if candidate_image is not None else ""),
            "is_social_media": bool(best.social),
            "face_similarity": fmt_score(best.face_similarity),
            "face_cosine_threshold": fmt_score(settings.face_cosine_threshold),
            "phash_distance": int(best.phash_distance or 0),
            "phash_max_distance": int(settings.phash_max_distance),
            "faces_in_matched_image": int(best.faces_in_candidate),
            "provider_position": int(best.candidate.position),
            "require_face_match": bool(require_face_match),
            "claim": claim,
            "limitations": limitations_for(best.status),
        },
        evidence_type=best.evidence_type,
        test_mode={
            "stub_engine": bool(stub_engine),
            "offline_fixture_provider": bool(provider.is_offline_stub),
        }
        if (stub_engine or provider.is_offline_stub)
        else None,
    )

    record = seal(payload)
    verification_hash = record["integrity"]["verification_hash"]
    ui.ok(
        f"payload canonicalized ({record['integrity']['canonical_length']} bytes, {record['integrity']['algorithm']})"
    )
    ui.field("evidence type", best.evidence_type)
    ui.field("verification hash", verification_hash)

    # -- stage 6: anchor ---------------------------------------------------
    ui.step("Anchoring on-chain" if not dry_run else "Anchoring (SIMULATED local chain)")
    client = build_chain_client(settings, dry_run=dry_run)
    if dry_run:
        ui.warn("--dry-run: writing to a SIMULATED local file, not a blockchain")
    described = client.describe()
    ui.info(f"network {described.get('network')} (chain id {described.get('chain_id')})")
    ui.info("only the payload hash and a keccak256 URL commitment are sent - not the URL")
    if isinstance(client, EvmChainClient) and client.account is not None:
        try:
            ui.info(f"signer {client.account.address}  balance {client.balance_eth():.6f} ETH")
        except Exception:  # noqa: BLE001
            pass

    anchor = client.register(verification_hash, best.candidate.page_url)
    ui.ok(f"transaction confirmed in block {anchor.block_number}")
    ui.field("tx hash", anchor.tx_hash)
    if anchor.explorer_url:
        ui.field("explorer", anchor.explorer_url)
    if anchor.gas_used:
        ui.field("gas used", f"{anchor.gas_used:,}")

    attach_anchor(record, anchor.to_json())
    out_path = Path(output) if output else (settings.output_dir / "verification.json")
    save_record(record, out_path)
    bundle.write_json("verification.json", record)
    bundle.write_json("anchor.json", anchor.to_json())
    bundle.finalize()

    ui.step("Done")
    ui.field("record", str(out_path))
    ui.field("evidence", str(bundle.dir))
    ui.out()
    ui.out(f"  Verify it with:  python -m src.main verify --record {out_path}")
    return EXIT_OK


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


def _check(status: str, detail: str = "") -> dict[str, str]:
    return {"status": status, "detail": detail}


def run_verify(
    settings: Settings,
    record_path: str | Path,
    *,
    dry_run: bool = False,
    image_path: str | Path | None = None,
    evidence_dir: str | Path | None = None,
    console: Console | None = None,
    report: dict[str, Any] | None = None,
) -> int:
    """Verify a record. Returns an exit code and fills *report* (if given).

    Check statuses are ``pass``, ``fail``, ``error`` (the check could not be
    completed) or ``skipped`` (not requested / not reached). ``verified`` is
    returned only when local integrity, the chain anchor and the URL commitment
    all *passed*; an ``error`` anywhere yields ``inconclusive``, never success.
    """
    ui = console or Console()
    report = report if report is not None else {}
    checks: dict[str, dict[str, str]] = {
        "local_integrity": _check("skipped"),
        "image_binding": _check("skipped", "not requested (pass --image)"),
        "evidence_bundle": _check("skipped", "not requested (pass --evidence-dir)"),
        "chain_anchor": _check("skipped"),
        "url_commitment": _check("skipped"),
    }
    report.update({"checks": checks, "simulated": False, "test_only": False})

    def finish(status: Status, *, message: str = "") -> int:
        report["verdict"] = _VERDICT_NAMES[status]
        report["exit_code"] = status.exit_code
        if message:
            report["message"] = message
        _verdict(ui, status, report)
        return status.exit_code

    ui.header("Image provenance verification  -  VERIFY")

    record = load_record(record_path)
    payload = record["payload"]
    anchor = record.get("anchor") or {}
    match = payload.get("match") or {}
    matched_url = match.get("matched_url", "")
    report["record_file"] = str(record_path)
    report["evidence_type"] = payload.get("evidence_type") or "unspecified (historical record)"
    report["test_only"] = bool(payload.get("test_mode"))

    ui.step("Record")
    ui.field("file", str(record_path))
    ui.field("schema", str(record.get("schema", "")))
    ui.field("evidence type", str(report["evidence_type"]))
    ui.field("decision rule", str(match.get("decision_rule", "")))
    ui.field("matched url", str(matched_url))
    ui.field("created at", str(payload.get("created_at", "")))
    if payload.get("test_mode"):
        ui.banner(
            [
                "TEST-ONLY RECORD: produced with a stub engine and/or offline fixture.",
                "It was not made by real face analysis or a real search.",
            ]
        )

    # -- step 1: local self-consistency -----------------------------------
    ui.step("Step 1  -  recomputing the hash from the payload")
    check = check_local_integrity(record)
    report["record_hash"] = check.recomputed_hash or check.stored_hash
    ui.field("algorithm", check.algorithm or "(none)")
    ui.field("stored hash", check.stored_hash or "(none)")
    ui.field("recomputed hash", check.recomputed_hash or "(not computed)")
    for note in check.notes:
        ui.warn(note)

    if not check.ok:
        reason = check.error or "the payload does not match its stored hash"
        checks["local_integrity"] = _check("fail", reason)
        ui.fail(f"INTEGRITY FAILURE  -  {reason}")
        ui.info("this record has been modified since it was sealed, or cannot be checked")
        return finish(Status.LOCAL_HASH_MISMATCH)
    checks["local_integrity"] = _check("pass", "payload matches its stored hash")
    ui.ok("HASH MATCH  -  payload is internally consistent")

    # -- step 2: optional binding to the image on disk ---------------------
    if image_path:
        ui.step("Step 2  -  checking the record against the image file")
        declared = str((payload.get("source_image") or {}).get("sha256", ""))
        actual = sha256_file(image_path)
        ui.field("record image sha256", declared)
        ui.field("file image sha256", actual)
        if declared.lower() != actual.lower():
            checks["image_binding"] = _check("fail", "image digest differs from the record")
            ui.fail("this record does not describe that image file")
            return finish(Status.LOCAL_HASH_MISMATCH)
        checks["image_binding"] = _check("pass", "image file matches source_image.sha256")
        ui.ok("the record describes exactly this image file")
    else:
        ui.step("Step 2  -  image binding NOT checked (pass --image to check it)")

    # -- step 2b: optional evidence bundle ---------------------------------
    if evidence_dir:
        ui.step("Step 2b  -  checking the evidence bundle against its manifest")
        bundle_check = verify_bundle(evidence_dir, record)
        if not bundle_check.ok:
            checks["evidence_bundle"] = _check("fail", "; ".join(bundle_check.problems)[:300])
            for problem in bundle_check.problems:
                ui.fail(problem)
            ui.info("the manifest alone cannot prove the bundle is pristine; see README")
            return finish(Status.LOCAL_HASH_MISMATCH)
        checks["evidence_bundle"] = _check(
            "pass", f"{bundle_check.files_checked} file(s) match the manifest and the record"
        )
        ui.ok(f"{bundle_check.files_checked} file(s) match the manifest and the record")

    # -- step 3: the chain ------------------------------------------------
    ui.step("Step 3  -  looking the hash up on-chain")
    if anchor.get("simulated") and not dry_run:
        ui.warn("this record was anchored to the SIMULATED chain; re-checking there")
        dry_run = True
    report["simulated"] = bool(dry_run)

    try:
        # No private key is needed to read: verification is permissionless.
        client = build_chain_client(settings, dry_run=dry_run, require_signer=False)
    except ConfigError:
        raise
    except ChainError as exc:
        checks["chain_anchor"] = _check("error", str(exc)[:300])
        checks["url_commitment"] = _check("error", "not run: chain unavailable")
        ui.fail(f"cannot complete the chain check: {exc}")
        return finish(Status.INCONCLUSIVE, message=str(exc)[:300])

    described = client.describe()
    report["chain"] = {
        k: described.get(k)
        for k in ("network", "chain_id", "contract_address", "registry_version")
        if described.get(k) is not None
    }
    ui.info(f"network {described.get('network')} (chain id {described.get('chain_id')})")
    ui.info(f"contract {described.get('contract_address') or described.get('store')}")

    try:
        chain_record = client.lookup(check.recomputed_hash)
    except ChainError as exc:
        checks["chain_anchor"] = _check("error", str(exc)[:300])
        checks["url_commitment"] = _check("error", "not run: lookup failed")
        ui.fail(f"chain lookup could not be completed: {exc}")
        ui.info("this is NOT a mismatch and NOT a success; the check did not run")
        return finish(Status.INCONCLUSIVE, message=str(exc)[:300])

    if not chain_record.exists:
        checks["chain_anchor"] = _check("fail", "hash is not registered")
        ui.fail("NOT ANCHORED  -  this hash is not registered on-chain")
        ui.info(
            "either the record was never registered, or its payload was altered and "
            "re-sealed - a re-sealed record is internally consistent but its new hash "
            "was never anchored, which is exactly what the chain is here to catch"
        )
        if anchor.get("tx_hash"):
            ui.info(f"the record claims tx {anchor['tx_hash']}")
        if anchor.get("registry_version") is None and not dry_run:
            ui.info(
                "this record has no registry_version: if it was anchored on an older "
                "(v1) deployment, this build's v2 contract cannot see that registration"
            )
        return finish(Status.NOT_ANCHORED)

    checks["chain_anchor"] = _check("pass", "hash found on-chain")
    ui.ok("ANCHORED  -  hash found on-chain")
    ui.field("submitter", chain_record.submitter)
    ui.field("block number", str(chain_record.block_number))
    ui.field("block timestamp", _fmt_ts(chain_record.timestamp))
    report["chain"].update(
        {
            "submitter": chain_record.submitter,
            "block_number": chain_record.block_number,
            "block_timestamp": chain_record.timestamp,
            "tx_hash": anchor.get("tx_hash", ""),
            "explorer_url": anchor.get("explorer_url", ""),
        }
    )
    if anchor.get("explorer_url"):
        ui.field("explorer", str(anchor["explorer_url"]))

    # Cross-check the URL, so a record cannot keep a valid anchor while
    # pointing the reader at a different post. A check that does not run is
    # NEVER treated as a pass.
    if not isinstance(matched_url, str) or not matched_url:
        checks["url_commitment"] = _check("fail", "record has no matched_url to check")
        ui.fail("the record has no matched_url, so the URL commitment cannot match")
        return finish(Status.ANCHOR_MISMATCH)
    try:
        url_ok = client.matches_url(check.recomputed_hash, matched_url)
    except Exception as exc:  # noqa: BLE001
        checks["url_commitment"] = _check("error", str(exc)[:300])
        ui.fail(f"the URL commitment check could not be completed: {exc}")
        ui.info("the record is anchored, but this record is NOT fully verified")
        return finish(Status.INCONCLUSIVE, message=str(exc)[:300])
    if not url_ok:
        checks["url_commitment"] = _check("fail", "on-chain commitment differs from matched_url")
        ui.fail("the on-chain URL commitment does NOT match the record's matched_url")
        return finish(Status.ANCHOR_MISMATCH)
    checks["url_commitment"] = _check("pass", "keccak256(matched_url) equals the on-chain commitment")
    ui.ok("the on-chain URL commitment matches the record's matched_url")

    claimed_block = anchor.get("block_number")
    if isinstance(claimed_block, int) and claimed_block != chain_record.block_number:
        ui.warn(f"the record claims block {claimed_block} but the chain says {chain_record.block_number}")
        report.setdefault("warnings", []).append("anchor block number differs from the chain")

    return finish(Status.OK)


def _fmt_ts(timestamp: int) -> str:
    if not timestamp:
        return "0"
    return f"{timestamp}  ({datetime.fromtimestamp(timestamp, tz=timezone.utc):%Y-%m-%d %H:%M:%S} UTC)"


def _verdict(ui: Console, status: Status, report: dict[str, Any]) -> None:
    checks = report.get("checks", {})
    ui.out()
    ui.rule()
    if status is Status.OK:
        ui.out(f"  {ui.tick} RECORD VERIFIED: UNMODIFIED, ANCHORED, URL COMMITMENT MATCHES")
        ui.out("    Passed: hash recomputation, chain anchor, URL commitment.")
        not_run = [n for n, c in checks.items() if c["status"] == "skipped"]
        if not_run:
            ui.out(f"    Not checked: {', '.join(not_run)}.")
        ui.out("    This shows the record is unchanged since it was registered. It does")
        ui.out("    not prove the underlying claim (see 'What this does not prove').")
        if report.get("simulated"):
            ui.out()
            ui.out("    SIMULATED: this was checked against a local JSON file, NOT a")
            ui.out("    blockchain. It is a rehearsal, not an on-chain anchor.")
        if report.get("test_only"):
            ui.out("    TEST-ONLY: the record itself came from a stub engine/fixture.")
    elif status is Status.LOCAL_HASH_MISMATCH:
        ui.out(f"  {ui.cross} RECORD FAILED LOCAL CHECKS (modified, wrong image, or unverifiable)")
    elif status is Status.NOT_ANCHORED:
        ui.out(f"  {ui.cross} RECORD IS NOT ANCHORED ON-CHAIN")
    elif status is Status.INCONCLUSIVE:
        ui.out("  ? VERIFICATION INCONCLUSIVE: a required check could not be completed")
        for name, check in checks.items():
            if check["status"] == "error":
                ui.out(f"    - {name}: {check['detail'][:100]}")
        ui.out("    Nothing is claimed either way. Fix the cause and re-run.")
    else:
        ui.out(f"  {ui.cross} RECORD CONFLICTS WITH THE ON-CHAIN ANCHOR")
    ui.out(f"    exit code {status.exit_code}")
    ui.rule()
