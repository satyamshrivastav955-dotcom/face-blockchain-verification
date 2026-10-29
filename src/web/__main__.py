"""Run the local web app:  python -m src.web   (binds to 127.0.0.1 only by default)."""

from __future__ import annotations

import argparse
import sys

from ..config import load_settings
from .app import create_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.web", description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: loopback only)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--env", default="", help="path to .env")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="enable the stub engine and offline fixture provider (NOT real verification; labelled in the UI)",
    )
    parser.add_argument(
        "--allow-chain-writes",
        action="store_true",
        help="allow the UI to register on the REAL chain (spends gas). Default: simulated chain only.",
    )
    args = parser.parse_args(argv)

    try:
        import uvicorn
    except ImportError:
        print("uvicorn is not installed: pip install -r requirements-web.txt", file=sys.stderr)
        return 1

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(
            f"WARNING: binding to {args.host} exposes this app, which has no authentication, "
            "to other machines. Do not do this on an untrusted network.",
            file=sys.stderr,
        )
    allowed = {"127.0.0.1", "localhost", "::1"} | ({args.host} if args.host not in ("0.0.0.0", "::") else set())
    app = create_app(
        load_settings(args.env or None),
        demo=args.demo,
        allow_chain_writes=args.allow_chain_writes,
        allowed_hosts=allowed,
    )
    print(
        f"FaceProof (local) on http://{args.host}:{args.port}  demo={args.demo}  chain_writes={args.allow_chain_writes}"
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
