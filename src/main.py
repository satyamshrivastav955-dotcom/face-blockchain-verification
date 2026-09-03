"""
Command-line entry point.

    python -m src.main doctor
    python -m src.main deploy
    python -m src.main register --image input/sample.jpg
    python -m src.main verify   --record output/verification.json
    python -m src.main tamper-demo --record output/verification.json

EXIT CODES
==========
The verifier's exit code is part of its output, not decoration: a grader (or a
CI job) can tell *how* a record failed without parsing prose.

    0  verified / success
    1  error (bad arguments, missing config, network or model failure)
    2  local hash mismatch      - the payload was edited after sealing
    3  not anchored on-chain    - the hash was never registered
    4  anchor mismatch          - anchored, but conflicts with the record
    5  no confirmed match       - the pipeline ran and honestly found nothing

WHY THE IMPORTS ARE LAZY
========================
``doctor`` exists to diagnose a broken environment, so it must run *before*
OpenCV, web3 or solcx are importable. Every heavyweight import therefore lives
inside the command that needs it, and a missing dependency produces an
explanation rather than a traceback at module load.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import PROJECT_ROOT, ConfigError, Settings, load_settings

__all__ = ["main", "build_parser"]

# Mirrors src.pipeline; duplicated so that --help and error handling work even
# when OpenCV cannot be imported.
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NO_MATCH = 5

EPILOG = """\
examples:
  python -m src.main doctor
      Check the environment before anything else: dependencies, model files,
      .env, wallet balance and whether the contract is reachable.

  python -m src.main deploy --save
      Compile and deploy VerificationRegistry, writing CONTRACT_ADDRESS to .env.

  python -m src.main register --image input/sample.jpg
      Full pipeline: detect a face, reverse-image search, confirm candidates
      locally, then anchor the sealed record on Base Sepolia.

  python -m src.main verify --record output/verification.json --image input/sample.jpg
      Recompute the hash, bind it to the image file, and look it up on-chain.

  python -m src.main tamper-demo --record output/verification.json
      Show both tamper classes: a naive edit (caught offline) and a re-sealed
      edit (only the blockchain catches it).

exit codes:
  0 ok   1 error   2 hash mismatch   3 not anchored   4 anchor mismatch
  5 no confirmed match
"""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _console(args: argparse.Namespace):
    from .ui import Console

    return Console(force_ascii=getattr(args, "ascii", False))


def _settings(args: argparse.Namespace) -> Settings:
    settings = load_settings(getattr(args, "env", None) or None)

    fixture = getattr(args, "fixture", "")
    if fixture:
        settings.fixture_path = fixture
        # A fixture is only meaningful to the offline provider, so passing one
        # selects it - but never silently overrides an explicit --provider.
        if not getattr(args, "provider", ""):
            args.provider = "local_fixture"

    if getattr(args, "rpc_url", ""):
        settings.rpc_url = args.rpc_url
    if getattr(args, "contract", ""):
        settings.contract_address = args.contract
    return settings


def _mask(value: str, *, reveal_tail: bool = True) -> str:
    """Describe a secret without disclosing it.

    Used by ``doctor``, which is likely to be on screen during the recording.
    The last four characters are shown for API keys, which is enough to tell
    two keys apart when something is misconfigured. For a private key even that
    is withheld: knowing which key is loaded is not worth narrowing the
    keyspace on camera, and the signer's public address (printed by the network
    check) already identifies it unambiguously.
    """
    if not value:
        return "not set"
    if len(value) <= 8:
        return "set"
    if not reveal_tail:
        return f"set ({len(value)} chars)"
    return f"set ({len(value)} chars, ends ...{value[-4:]})"


def _resolve(path_str: str) -> Path:
    path = Path(path_str)
    return path if path.is_absolute() else (Path.cwd() / path)


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------


def cmd_register(args: argparse.Namespace) -> int:
    settings = _settings(args)
    ui = _console(args)

    image = _resolve(args.image)
    if not image.exists():
        ui.fail(f"no such image: {image}")
        ui.info("put a photo in input/ and pass it with --image input/<file>.jpg")
        return EXIT_ERROR

    from .pipeline import run_register

    return run_register(
        settings,
        image,
        provider_name=args.provider,
        engine_name=args.engine,
        image_url=args.image_url,
        dry_run=args.dry_run,
        max_candidates=args.max_candidates,
        stop_early=args.stop_early,
        allow_offline_stub=args.allow_offline_stub,
        output=args.output,
        console=ui,
    )


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


def cmd_verify(args: argparse.Namespace) -> int:
    settings = _settings(args)
    ui = _console(args)

    record = _resolve(args.record)
    if not record.exists():
        ui.fail(f"no such record: {record}")
        ui.info("run 'register' first, or pass --record <path to verification.json>")
        return EXIT_ERROR

    from .pipeline import run_verify

    return run_verify(
        settings,
        record,
        dry_run=args.dry_run,
        image_path=_resolve(args.image) if args.image else None,
        console=ui,
    )


# ---------------------------------------------------------------------------
# tamper-demo
# ---------------------------------------------------------------------------


def cmd_tamper_demo(args: argparse.Namespace) -> int:
    """Forge the record two ways and verify each, without touching the original.

    This is the clearest way to show what the blockchain is actually for. A
    naive edit is caught by arithmetic alone; the re-sealed edit is internally
    perfect and is caught *only* because its new hash was never anchored.
    """
    from .record import (
        check_local_integrity,
        load_record,
        mutate_payload,
        save_record,
        seal,
    )

    settings = _settings(args)
    ui = _console(args)

    source = _resolve(args.record)
    if not source.exists():
        ui.fail(f"no such record: {source}")
        return EXIT_ERROR

    ui.header("Tamper demonstration  -  two classes of forgery")
    ui.info(f"original record: {source}")
    ui.info("the original file is never modified; forgeries are written alongside it")

    original = load_record(source)
    genuine_hash = str((original.get("integrity") or {}).get("verification_hash", ""))
    ui.field("genuine hash", genuine_hash)
    ui.field("field to alter", args.field)

    try:
        preview = load_record(source)
        old_value = mutate_payload(preview, args.field, args.value)
    except KeyError as exc:
        ui.fail(str(exc))
        ui.info("pass --field with a dotted path that exists, e.g. match.matched_url")
        return EXIT_ERROR

    ui.field("current value", str(old_value))
    ui.field("forged value", str(args.value))

    results: list[tuple[str, int]] = []
    modes = ["naive", "resealed"] if args.mode == "both" else [args.mode]

    for mode in modes:
        forged = load_record(source)
        mutate_payload(forged, args.field, args.value)

        if mode == "naive":
            # Leave integrity.verification_hash untouched: the classic clumsy edit.
            out = source.with_name(source.stem + ".tampered-naive.json")
            title = "Forgery 1 of 2  -  naive edit (hash left alone)"
            explain = (
                "The attacker edits the payload and forgets the hash. The file "
                "now contradicts itself, so this is caught offline, instantly, "
                "with no network and no blockchain."
            )
        else:
            # Recompute the hash so the file is internally flawless again.
            anchor = forged.get("anchor")
            forged = seal(forged["payload"])
            forged["anchor"] = anchor  # keep the *old* tx, as a forger would
            out = source.with_name(source.stem + ".tampered-resealed.json")
            title = "Forgery 2 of 2  -  re-sealed edit (hash recomputed)"
            explain = (
                "The attacker edits the payload AND recomputes the hash. The "
                "file is now perfectly self-consistent - every offline check "
                "passes. It still carries the original transaction id, hoping "
                "no one looks. Only the chain can settle this."
            )

        save_record(forged, out)
        check = check_local_integrity(forged)

        ui.out()
        ui.rule()
        ui.out(f"  {title}")
        ui.rule()
        ui.info(explain)
        ui.out()
        ui.field("forged file", str(out))
        ui.field("hash in file", str((forged.get("integrity") or {}).get("verification_hash", "")))
        ui.field("hash recomputed", check.recomputed_hash)
        ui.field("internally consistent", "yes" if check.ok else "no")
        if mode == "resealed" and check.recomputed_hash.lower() != genuine_hash.lower():
            ui.info(
                "note: the re-sealed hash differs from the genuine one, so it "
                "cannot be present on-chain - that difference is the tell"
            )

        from .pipeline import run_verify

        code = run_verify(
            settings,
            out,
            dry_run=args.dry_run,
            image_path=None,
            console=ui,
        )
        results.append((mode, code))

    # -- the original, for contrast ---------------------------------------
    if args.verify_original:
        ui.out()
        ui.rule()
        ui.out("  Control  -  the untouched original")
        ui.rule()
        from .pipeline import run_verify

        code = run_verify(settings, source, dry_run=args.dry_run, console=ui)
        results.append(("original", code))

    ui.out()
    ui.rule()
    ui.out("  Summary")
    ui.rule()
    labels = {
        "naive": "naive edit        ",
        "resealed": "re-sealed edit    ",
        "original": "untouched original",
    }
    meanings = {0: "VERIFIED", 2: "REJECTED (hash mismatch)", 3: "REJECTED (not anchored)",
                4: "REJECTED (anchor mismatch)", 1: "ERROR"}
    for mode, code in results:
        ui.out(f"  {labels.get(mode, mode)}  exit {code}  {meanings.get(code, '')}")
    ui.out()
    ui.info("caught offline by the hash; caught on-chain by the anchor")

    # The demo itself succeeded as long as every forgery was rejected.
    forgeries = [code for mode, code in results if mode != "original"]
    return EXIT_OK if all(code != 0 for code in forgeries) else EXIT_ERROR


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def cmd_doctor(args: argparse.Namespace) -> int:
    """Pre-flight check. Run this before recording, not during."""
    ui = _console(args)
    ui.header("Environment check")

    problems: list[str] = []
    warnings: list[str] = []

    # -- python ------------------------------------------------------------
    ui.step("Python")
    version = sys.version_info
    ui.field("version", f"{version.major}.{version.minor}.{version.micro}")
    ui.field("executable", sys.executable)
    if version < (3, 9):
        problems.append(f"Python 3.9+ required, found {version.major}.{version.minor}")

    # -- dependencies ------------------------------------------------------
    ui.step("Dependencies")
    required = {
        "cv2": "opencv-python",
        "numpy": "numpy",
        "requests": "requests",
    }
    optional = {
        "dotenv": "python-dotenv (reads .env)",
        "web3": "web3 (needed to anchor and to verify on-chain)",
        "solcx": "py-solc-x (needed only to compile/deploy the contract)",
        "pytest": "pytest (needed only to run the test suite)",
    }
    for module, package in required.items():
        try:
            mod = __import__(module)
            ui.ok(f"{package:<22} {getattr(mod, '__version__', '')}")
        except ImportError:
            ui.fail(f"{package:<22} MISSING")
            problems.append(f"install it with: pip install {package.split()[0]}")
    for module, package in optional.items():
        try:
            mod = __import__(module)
            ui.ok(f"{package:<22} {getattr(mod, '__version__', '')}")
        except ImportError:
            ui.warn(f"{package} is not installed")
            warnings.append(f"optional: {package}")

    # -- models ------------------------------------------------------------
    ui.step("Face models")
    try:
        from .faces import DET_MODEL_FILE, REC_MODEL_FILE
    except ImportError:
        DET_MODEL_FILE = "face_detection_yunet_2023mar.onnx"
        REC_MODEL_FILE = "face_recognition_sface_2021dec.onnx"

    settings = _settings(args)
    for filename in (DET_MODEL_FILE, REC_MODEL_FILE):
        path = settings.models_dir / filename
        if not path.exists():
            ui.fail(f"{filename}  MISSING")
            problems.append("download the models with: python scripts/fetch_models.py")
        elif path.stat().st_size < 50_000:
            ui.fail(f"{filename}  only {path.stat().st_size} bytes (git-lfs pointer?)")
            problems.append(f"delete {path} and re-run scripts/fetch_models.py")
        else:
            ui.ok(f"{filename}  {path.stat().st_size / 1e6:.1f} MB")

    # -- configuration -----------------------------------------------------
    ui.step("Configuration")
    env_file = Path(getattr(args, "env", "") or (PROJECT_ROOT / ".env"))
    if env_file.exists():
        ui.ok(f".env found at {env_file}")
    else:
        ui.warn(f"no .env at {env_file} (copy .env.example and fill it in)")
        warnings.append("no .env file")

    ui.field("search provider", settings.search_provider)
    ui.field("SERPAPI_KEY", _mask(settings.serpapi_key))
    ui.field("TINEYE_API_KEY", _mask(settings.tineye_api_key))
    ui.field("publish provider", settings.publish_provider)
    ui.field("IMGBB_API_KEY", _mask(settings.imgbb_api_key))
    ui.field("chain", f"{settings.chain_name} (id {settings.chain_id})")
    ui.field("RPC_URL", settings.rpc_url or "not set")
    ui.field("CONTRACT_ADDRESS", settings.contract_address or "not set")
    ui.field("PRIVATE_KEY", _mask(settings.private_key, reveal_tail=False))
    ui.field("cosine threshold", str(settings.face_cosine_threshold))
    ui.field("pHash max distance", str(settings.phash_max_distance))

    if settings.search_provider in ("serpapi_lens", "serpapi", "lens") and not settings.serpapi_key:
        problems.append("SEARCH_PROVIDER is serpapi_lens but SERPAPI_KEY is not set")
    if settings.search_provider == "tineye" and not settings.tineye_api_key:
        problems.append("SEARCH_PROVIDER is tineye but TINEYE_API_KEY is not set")

    # -- contract artifact -------------------------------------------------
    ui.step("Contract")
    from .chain import ARTIFACT_PATH, CONTRACT_SOURCE

    ui.field("source", "present" if CONTRACT_SOURCE.exists() else "MISSING")
    if not CONTRACT_SOURCE.exists():
        problems.append(f"contract source missing at {CONTRACT_SOURCE}")
    if ARTIFACT_PATH.exists():
        ui.ok(f"compiled artifact present ({ARTIFACT_PATH.name})")
    else:
        ui.warn("not compiled yet - 'deploy' will compile it (needs solc, one-off download)")

    # -- network -----------------------------------------------------------
    if args.offline:
        ui.step("Network checks skipped (--offline)")
    else:
        ui.step("Network")
        try:
            from .chain import ChainError, EvmChainClient

            client = EvmChainClient(settings, require_signer=bool(settings.private_key))
            ui.ok(f"connected to {settings.rpc_url}")
            ui.field("chain id", str(client.w3.eth.chain_id))
            ui.field("latest block", str(client.w3.eth.block_number))
            if client.account is not None:
                balance = client.balance_eth()
                ui.field("signer address", client.account.address)
                ui.field("balance", f"{balance:.6f} ETH")
                if balance <= 0:
                    problems.append(
                        "the signer has no testnet ETH - fund it from a Base Sepolia "
                        "faucet before running register"
                    )
                elif balance < 0.0005:
                    warnings.append("signer balance is very low; top up before the demo")
            else:
                ui.warn("PRIVATE_KEY not set - reads will work, anchoring will not")
            if client.contract is not None:
                total = client.contract.functions.totalRecords().call()
                ui.ok(f"contract reachable, {total} record(s) registered")
            else:
                ui.warn("CONTRACT_ADDRESS not set - run 'deploy' first")
                warnings.append("contract not deployed")
        except Exception as exc:  # noqa: BLE001 - doctor reports, never raises
            ui.fail(f"chain check failed: {exc}")
            problems.append(str(exc))

    # -- summary -----------------------------------------------------------
    # Deduplicated while preserving order: two missing models produce the same
    # "download the models" instruction, and printing it twice reads like two
    # separate things to do.
    ui.step("Summary")
    for warning in dict.fromkeys(warnings):
        ui.warn(warning)
    unique = list(dict.fromkeys(problems))
    if unique:
        for problem in unique:
            ui.fail(problem)
        ui.out()
        ui.fail(f"{len(unique)} problem(s) to fix before the pipeline will run")
        return EXIT_ERROR
    ui.ok("environment looks ready")
    return EXIT_OK


# ---------------------------------------------------------------------------
# deploy
# ---------------------------------------------------------------------------


def _write_env_value(env_path: Path, key: str, value: str) -> None:
    """Set ``key=value`` in *env_path*, preserving everything else.

    Rewrites the matching line in place rather than appending, so repeated
    deploys do not leave a trail of stale CONTRACT_ADDRESS lines where the last
    one silently wins.
    """
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    replaced = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
            lines[index] = f"{key}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_deploy(args: argparse.Namespace) -> int:
    settings = _settings(args)
    ui = _console(args)
    ui.header("Deploy VerificationRegistry")

    from .chain import ARTIFACT_PATH, EvmChainClient, compile_contract

    ui.step("Compiling")
    artifact = compile_contract(force=args.force_compile)
    ui.ok(f"solc {artifact['solcVersion']}, {len(artifact['bytecode']) // 2} bytes of bytecode")
    ui.field("artifact", str(ARTIFACT_PATH))
    ui.field("source sha256", artifact.get("sourceSha256", ""))

    if args.compile_only:
        ui.ok("compile-only: not deploying")
        return EXIT_OK

    if settings.contract_address and not args.force:
        ui.warn(f"CONTRACT_ADDRESS is already set to {settings.contract_address}")
        ui.info("deploying again would create a second, unrelated registry")
        ui.info("pass --force if that is genuinely what you want")
        return EXIT_ERROR

    ui.step("Connecting")
    # A fresh deploy must not adopt the old address from .env.
    settings.contract_address = ""
    client = EvmChainClient(settings, require_signer=True)
    ui.field("network", f"{settings.chain_name} (id {settings.chain_id})")
    ui.field("deployer", client.account.address)
    balance = client.balance_eth()
    ui.field("balance", f"{balance:.6f} ETH")
    if balance <= 0:
        ui.fail("the deployer has no testnet ETH")
        ui.info("fund it from a Base Sepolia faucet, then try again")
        return EXIT_ERROR

    ui.step("Deploying")
    address, tx_hash = client.deploy()
    if not tx_hash.startswith("0x"):
        tx_hash = "0x" + tx_hash
    ui.ok("contract deployed")
    ui.field("address", address)
    ui.field("tx hash", tx_hash)
    ui.field("explorer", settings.address_url(address))

    env_path = Path(getattr(args, "env", "") or (PROJECT_ROOT / ".env"))
    if args.save:
        _write_env_value(env_path, "CONTRACT_ADDRESS", address)
        ui.ok(f"CONTRACT_ADDRESS written to {env_path}")
    else:
        ui.out()
        ui.info("add this line to your .env:")
        ui.out(f"    CONTRACT_ADDRESS={address}")
    return EXIT_OK


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.main",
        description=(
            "Face ID + blockchain verification: match a face against a real "
            "social-media post found by reverse-image search, then anchor the "
            "result on-chain."
        ),
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--env", default="", metavar="PATH", help="path to .env (default: ./.env)")
    common.add_argument(
        "--ascii",
        action="store_true",
        help="force plain ASCII output (use on a legacy Windows console)",
    )

    chain_opts = argparse.ArgumentParser(add_help=False)
    chain_opts.add_argument("--rpc-url", default="", metavar="URL", help="override RPC_URL")
    chain_opts.add_argument(
        "--contract", default="", metavar="ADDRESS", help="override CONTRACT_ADDRESS"
    )
    chain_opts.add_argument(
        "--dry-run",
        action="store_true",
        help="use the simulated local chain instead of the real network",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    # -- register ----------------------------------------------------------
    register = subparsers.add_parser(
        "register",
        parents=[common, chain_opts],
        help="run the full pipeline and anchor the result",
        description="Detect a face, search for it, confirm the match, anchor the record.",
    )
    register.add_argument("--image", required=True, metavar="PATH", help="input photo")
    register.add_argument(
        "--provider",
        default="",
        metavar="NAME",
        help="reverse-search backend: serpapi_lens, tineye, local_fixture",
    )
    register.add_argument(
        "--engine", default="opencv", metavar="NAME", help="face engine: opencv (default) or stub"
    )
    register.add_argument(
        "--image-url",
        default="",
        metavar="URL",
        help="public URL of the query image (skips uploading it)",
    )
    register.add_argument(
        "--max-candidates", type=int, default=None, metavar="N", help="cap candidates checked"
    )
    register.add_argument(
        "--stop-early",
        action="store_true",
        help="stop at the first confirmed social-media match (faster, less evidence)",
    )
    register.add_argument(
        "--fixture", default="", metavar="PATH", help="offline candidate fixture (implies local_fixture)"
    )
    register.add_argument(
        "--allow-offline-stub",
        action="store_true",
        help="permit the stub engine / fixture provider - NOT a real verification",
    )
    register.add_argument("--output", default="", metavar="PATH", help="where to write the record")
    register.set_defaults(func=cmd_register)

    # -- verify ------------------------------------------------------------
    verify = subparsers.add_parser(
        "verify",
        parents=[common, chain_opts],
        help="check a record against its hash and the chain",
        description="Recompute the hash, optionally bind it to an image, then query the chain.",
    )
    verify.add_argument(
        "--record", default="output/verification.json", metavar="PATH", help="record to verify"
    )
    verify.add_argument(
        "--image", default="", metavar="PATH", help="also check the record describes this file"
    )
    verify.set_defaults(func=cmd_verify)

    # -- tamper-demo -------------------------------------------------------
    tamper = subparsers.add_parser(
        "tamper-demo",
        parents=[common, chain_opts],
        help="demonstrate that edits are detected",
        description=(
            "Produce two forgeries of a record and verify each: a naive edit "
            "(caught offline) and a re-sealed edit (caught only by the chain). "
            "The original file is never modified."
        ),
    )
    tamper.add_argument(
        "--record", default="output/verification.json", metavar="PATH", help="record to forge"
    )
    tamper.add_argument(
        "--field",
        default="match.matched_url",
        metavar="DOTTED.PATH",
        help="payload field to alter (default: match.matched_url)",
    )
    tamper.add_argument(
        "--value",
        default="https://instagram.com/p/ATTACKER_SWAPPED_THIS/",
        metavar="VALUE",
        help="value to write into that field",
    )
    tamper.add_argument(
        "--mode",
        choices=("naive", "resealed", "both"),
        default="both",
        help="which forgery to demonstrate (default: both)",
    )
    tamper.add_argument(
        "--verify-original",
        action="store_true",
        help="also verify the untouched original, as a control",
    )
    tamper.set_defaults(func=cmd_tamper_demo)

    # -- doctor ------------------------------------------------------------
    doctor = subparsers.add_parser(
        "doctor",
        parents=[common, chain_opts],
        help="check dependencies, models, config and wallet",
        description="Pre-flight check. Never prints secrets.",
    )
    doctor.add_argument("--offline", action="store_true", help="skip all network checks")
    doctor.set_defaults(func=cmd_doctor)

    # -- deploy ------------------------------------------------------------
    deploy = subparsers.add_parser(
        "deploy",
        parents=[common, chain_opts],
        help="compile and deploy the registry contract",
        description="Compile VerificationRegistry.sol and deploy it to the configured chain.",
    )
    deploy.add_argument("--save", action="store_true", help="write CONTRACT_ADDRESS into .env")
    deploy.add_argument("--force", action="store_true", help="deploy even if one is already set")
    deploy.add_argument("--force-compile", action="store_true", help="recompile, ignoring the cache")
    deploy.add_argument("--compile-only", action="store_true", help="compile without deploying")
    deploy.set_defaults(func=cmd_deploy)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        parser.print_help()
        return EXIT_ERROR

    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except ConfigError as exc:
        print(f"\nconfiguration error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except FileNotFoundError as exc:
        print(f"\nfile not found: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except Exception as exc:  # noqa: BLE001
        # Domain errors carry actionable messages, so print them plainly; an
        # unexpected error still gets a traceback via --debug.
        name = type(exc).__name__
        known = {
            "ChainError",
            "SearchError",
            "PublishError",
            "ModelMissingError",
            "NoFaceError",
            "CanonicalizationError",
            "ImageError",
        }
        if name in known:
            print(f"\n{name}: {exc}", file=sys.stderr)
            return EXIT_ERROR
        raise


if __name__ == "__main__":
    sys.exit(main())
