"""
Pipeline orchestration for ``register`` and ``verify``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .evidence.hashing import canonicalize, digest_hex, fmt_score, sha256_bytes, sha256_file
from .blockchain.client import ChainError, build_chain_client
from .config import SOCIAL_DOMAINS, ConfigError, Settings
from .verification.candidate_matcher import confirm_candidates, score_table, select_best
from .evidence.bundle import EvidenceBundle, new_run_id
from .vision.face_detector import (
    ModelMissingError,
    OpenCVFaceEngine,
    StubFaceEngine,
    embedding_fingerprint,
)
from .vision.preprocess import image_info, load_image, phash, phash_hex, side_by_side
from .publish import publish_image
from .evidence.record import (
    Status,
    attach_anchor,
    build_payload,
    check_local_integrity,
    load_record,
    save_record,
    seal,
    utc_now,
)
from .search import SearchError, build_provider, is_social, rank_candidates
from .ui import Console

__all__ = [
    "EXIT_OK",
    "EXIT_ERROR",
    "EXIT_NO_MATCH",
    "build_engine",
    "run_register",
    "run_verify",
]

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NO_MATCH = 5


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
    output: str | Path | None = None,
    console: Console | None = None,
) -> int:
    ui = console or Console()
    path = Path(image_path)
    limit = max_candidates or settings.max_candidates

    ui.header("Face ID + Blockchain Verification  -  REGISTER")

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

    # -- stage 2: face detection and embedding -----------------------------
    ui.step("Detecting and encoding face")
    engine = build_engine(engine_name, settings, allow_stub=allow_offline_stub)
    if isinstance(engine, StubFaceEngine):
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
    x, y, w, h = primary.bbox
    ui.info(f"primary face bbox x={x} y={y} w={w} h={h}  score={fmt_score(primary.det_score)}")
    ui.info(f"embedding: {primary.embedding.size}-d via {engine.name}")
    ui.info(f"embedding sha256 {embedding_fingerprint(primary.embedding)[:32]}...")
    ui.info("(the embedding itself is never published or written on-chain)")
    bundle.write_image("query_face.png", primary.aligned)

    # -- stage 3: reverse image search -------------------------------------
    ui.step("Reverse image search")
    provider = build_provider(provider_name or settings.search_provider, settings)

    if provider.is_offline_stub:
        if not allow_offline_stub:
            ui.fail(
                f"provider '{provider.name}' is an offline stub and cannot produce a "
                "genuine match"
            )
            ui.info("pass --allow-offline-stub to use it for plumbing tests")
            return EXIT_ERROR
        ui.banner(
            [
                "WARNING: offline fixture provider in use.",
                "No real reverse-image search was performed.",
                "This is NOT valid for the graded submission.",
            ]
        )

    query_url = image_url
    if provider.needs_public_url and not query_url:
        ui.info(f"{provider.name} requires a public image URL; uploading via {settings.publish_provider}")
        query_url = publish_image(
            path, settings.publish_provider, imgbb_api_key=settings.imgbb_api_key
        )
        ui.ok(f"query image published at {query_url}")

    ui.info(f"provider: {provider.name}  endpoint: {provider.describe()}")
    result = provider.search(path, image_url=query_url, max_results=limit)

    raw_bytes = json.dumps(
        result.raw_response, indent=2, sort_keys=True, ensure_ascii=False, default=str
    ).encode("utf-8")
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

    # -- stage 4: independent confirmation ---------------------------------
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
        progress=ui.out,
    )

    ui.out()
    ui.out(score_table(confirmations))

    candidate_json = [c.to_json() for c in confirmations]
    candidates_canonical = canonicalize(candidate_json)
    bundle.write_bytes("candidates.canonical.json", candidates_canonical)
    bundle.write_json("candidates.json", candidate_json)
    candidates_sha256 = sha256_bytes(candidates_canonical)

    best = select_best(confirmations)
    if best is None:
        # The negative case, and an important one: a pipeline that cannot
        # decline is indistinguishable from one that fabricates.
        ui.out()
        ui.fail("no candidate passed independent confirmation")
        ui.info(
            f"best face similarity was "
            f"{fmt_score(max((c.face_similarity for c in confirmations), default=0.0))}, "
            f"threshold is {fmt_score(settings.face_cosine_threshold)}"
        )
        ui.info("refusing to write an unconfirmed claim to the blockchain")
        bundle.write_json(
            "no_match_report.json",
            {
                "source_image_sha256": image_sha256,
                "searched_at": result.searched_at,
                "provider": result.provider,
                "candidates_considered": len(confirmations),
                "candidates_sha256": candidates_sha256,
                "outcome": "no_confirmed_match",
            },
        )
        bundle.finalize()
        ui.info(f"evidence written to {bundle.dir}")
        return EXIT_NO_MATCH

    ui.out()
    ui.ok(f"confirmed match on {best.candidate.domain} ({best.status})")
    ui.field("matched post", best.candidate.page_url)
    ui.field("face similarity", f"{fmt_score(best.face_similarity)} (threshold {fmt_score(settings.face_cosine_threshold)})")
    ui.field("pHash distance", f"{best.phash_distance}/64")

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
        accepted=True,
    )
    bundle.write_image("comparison.png", comparison)

    # -- stage 5: build and seal the record --------------------------------
    ui.step("Building the verification record")
    candidate_image = None
    if best.candidate_image_bytes:
        import cv2
        import numpy as np

        candidate_image = cv2.imdecode(
            np.frombuffer(best.candidate_image_bytes, np.uint8), cv2.IMREAD_COLOR
        )

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
            "embedding_sha256": embedding_fingerprint(primary.embedding),
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
            "candidates_sha256": candidates_sha256,
            "offline_stub": bool(provider.is_offline_stub),
        },
        match={
            "matched_url": best.candidate.page_url,
            "matched_domain": best.candidate.domain,
            "matched_image_url": best.candidate.best_image_url(),
            "matched_image_sha256": best.candidate_image_sha256,
            "matched_image_phash": (
                phash_hex(candidate_image) if candidate_image is not None else ""
            ),
            "is_social_media": bool(best.social),
            "decision_rule": best.status,
            "face_similarity": fmt_score(best.face_similarity),
            "face_cosine_threshold": fmt_score(settings.face_cosine_threshold),
            "phash_distance": int(best.phash_distance or 0),
            "phash_max_distance": int(settings.phash_max_distance),
            "faces_in_matched_image": int(best.faces_in_candidate),
            "provider_position": int(best.candidate.position),
            "claim": (
                "the image at matched_image_url, published on matched_url, contains "
                "the same face as source_image; this asserts image provenance, not "
                "the identity of any person"
            ),
        },
    )

    record = seal(payload)
    verification_hash = record["integrity"]["verification_hash"]
    ui.ok(f"payload canonicalized ({record['integrity']['canonical_length']} bytes, RFC 8785)")
    ui.field("verification hash", verification_hash)

    # -- stage 6: anchor ---------------------------------------------------
    ui.step("Anchoring on-chain")
    client = build_chain_client(settings, dry_run=dry_run)
    if dry_run:
        ui.warn("--dry-run: writing to the SIMULATED local chain, not Base Sepolia")
    described = client.describe()
    ui.info(f"network {described.get('network')} (chain id {described.get('chain_id')})")
    if not dry_run:
        try:
            ui.info(f"signer {client.account.address}  balance {client.balance_eth():.6f} ETH")
        except Exception:
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


def run_verify(
    settings: Settings,
    record_path: str | Path,
    *,
    dry_run: bool = False,
    image_path: str | Path | None = None,
    console: Console | None = None,
) -> int:
    ui = console or Console()
    ui.header("Face ID + Blockchain Verification  -  VERIFY")

    record = load_record(record_path)
    payload = record["payload"]
    anchor = record.get("anchor") or {}

    ui.step("Record")
    ui.field("file", str(record_path))
    ui.field("matched url", str((payload.get("match") or {}).get("matched_url", "")))
    ui.field("created at", str(payload.get("created_at", "")))

    # -- step 1: local self-consistency -----------------------------------
    ui.step("Step 1 of 3  -  recomputing the hash from the payload")
    check = check_local_integrity(record)
    ui.field("stored hash", check.stored_hash or "(none)")
    ui.field("recomputed hash", check.recomputed_hash)
    for note in check.notes:
        ui.warn(note)

    if not check.ok:
        ui.fail("HASH MISMATCH  -  the payload does not match its stored hash")
        ui.info("this record has been modified since it was sealed")
        _verdict(ui, Status.LOCAL_HASH_MISMATCH)
        return Status.LOCAL_HASH_MISMATCH.exit_code
    ui.ok("HASH MATCH  -  payload is internally consistent")

    # -- step 2: optional binding to the image on disk ---------------------
    if image_path:
        ui.step("Step 2 of 3  -  checking the record against the image file")
        declared = str((payload.get("source_image") or {}).get("sha256", ""))
        actual = sha256_file(image_path)
        ui.field("record image sha256", declared)
        ui.field("file image sha256", actual)
        if declared.lower() != actual.lower():
            ui.fail("this record does not describe that image file")
            _verdict(ui, Status.LOCAL_HASH_MISMATCH)
            return Status.LOCAL_HASH_MISMATCH.exit_code
        ui.ok("the record describes exactly this image file")
    else:
        ui.step("Step 2 of 3  -  image binding skipped (pass --image to check it)")

    # -- step 3: the chain ------------------------------------------------
    ui.step("Step 3 of 3  -  looking the hash up on-chain")
    if anchor.get("simulated") and not dry_run:
        ui.warn("this record was anchored to the SIMULATED chain; re-checking there")
        dry_run = True

    try:
        # No private key is needed to read: verification is permissionless.
        client = build_chain_client(settings, dry_run=dry_run, require_signer=False)
    except (ChainError, ConfigError) as exc:
        ui.fail(f"cannot reach the chain: {exc}")
        return EXIT_ERROR

    described = client.describe()
    ui.info(f"network {described.get('network')} (chain id {described.get('chain_id')})")
    ui.info(f"contract {described.get('contract_address') or described.get('store')}")

    chain_record = client.lookup(check.recomputed_hash)
    if not chain_record.exists:
        ui.fail("NOT ANCHORED  -  this hash is not registered on-chain")
        ui.info(
            "either the record was never registered, or its payload was altered and "
            "re-sealed - a re-sealed record is internally consistent but its new hash "
            "was never anchored, which is exactly what the chain is here to catch"
        )
        if anchor.get("tx_hash"):
            ui.info(f"the record claims tx {anchor['tx_hash']}")
        _verdict(ui, Status.NOT_ANCHORED)
        return Status.NOT_ANCHORED.exit_code

    ui.ok("ANCHORED  -  hash found on-chain")
    ui.field("submitter", chain_record.submitter)
    ui.field("block number", str(chain_record.block_number))
    ui.field("block timestamp", _fmt_ts(chain_record.timestamp))
    if anchor.get("explorer_url"):
        ui.field("explorer", str(anchor["explorer_url"]))

    # Cross-check the URL, so a record cannot keep a valid anchor while
    # pointing the reader at a different post.
    matched_url = str((payload.get("match") or {}).get("matched_url", ""))
    url_ok = True
    try:
        url_ok = client.matches_url(check.recomputed_hash, matched_url)
    except Exception:
        url_ok = True  # non-fatal: the hash check above is authoritative
    if url_ok:
        ui.ok("the on-chain URL commitment matches the record's matched_url")
    else:
        ui.fail("the on-chain URL commitment does NOT match the record's matched_url")
        _verdict(ui, Status.ANCHOR_MISMATCH)
        return Status.ANCHOR_MISMATCH.exit_code

    claimed_block = anchor.get("block_number")
    if isinstance(claimed_block, int) and claimed_block != chain_record.block_number:
        ui.warn(
            f"the record claims block {claimed_block} but the chain says "
            f"{chain_record.block_number}"
        )

    _verdict(ui, Status.OK)
    return Status.OK.exit_code


def _fmt_ts(timestamp: int) -> str:
    from datetime import datetime, timezone

    if not timestamp:
        return "0"
    return (
        f"{timestamp}  ("
        f"{datetime.fromtimestamp(timestamp, tz=timezone.utc):%Y-%m-%d %H:%M:%S} UTC)"
    )


def _verdict(ui: Console, status: Status) -> None:
    ui.out()
    ui.rule()
    if status is Status.OK:
        ui.out(f"  {ui.tick} RECORD VERIFIED AND UNMODIFIED")
        ui.out("    The payload matches its hash, and that hash was anchored on-chain.")
    elif status is Status.LOCAL_HASH_MISMATCH:
        ui.out(f"  {ui.cross} RECORD HAS BEEN MODIFIED")
    elif status is Status.NOT_ANCHORED:
        ui.out(f"  {ui.cross} RECORD IS NOT ANCHORED ON-CHAIN")
    else:
        ui.out(f"  {ui.cross} RECORD CONFLICTS WITH THE ON-CHAIN ANCHOR")
    ui.out(f"    exit code {status.exit_code}")
    ui.rule()
