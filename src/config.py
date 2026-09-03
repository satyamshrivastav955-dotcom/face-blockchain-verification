"""Configuration loaded from the environment (.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

__all__ = ["Settings", "load_settings", "ConfigError", "PROJECT_ROOT"]

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Platforms whose pages count as "social media" for this assignment. Candidates
# on these domains are confirmed first, since the task asks specifically for a
# matching social-media post; others are still checked as a fallback.
SOCIAL_DOMAINS: tuple[str, ...] = (
    "instagram.com",
    "x.com",
    "twitter.com",
    "facebook.com",
    "fb.com",
    "linkedin.com",
    "reddit.com",
    "pinterest.com",
    "pinterest.co.uk",
    "tiktok.com",
    "threads.net",
    "threads.com",
    "tumblr.com",
    "vk.com",
    "weibo.com",
    "flickr.com",
    "mastodon.social",
    "bsky.app",
    "youtube.com",
    "snapchat.com",
)


class ConfigError(RuntimeError):
    """Configuration is missing or invalid."""


def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


def _env_int(key: str, default: int) -> int:
    raw = _env(key)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer, got {raw!r}") from exc


def _env_float(key: str, default: float) -> float:
    raw = _env(key)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be a number, got {raw!r}") from exc


@dataclass
class Settings:
    # search
    search_provider: str = "serpapi_lens"
    serpapi_key: str = ""
    tineye_api_key: str = ""
    fixture_path: str = ""

    # publishing
    publish_provider: str = "catbox"
    imgbb_api_key: str = ""

    # chain
    chain_name: str = "base-sepolia"
    chain_id: int = 84532
    rpc_url: str = "https://sepolia.base.org"
    explorer_base: str = "https://sepolia.basescan.org"
    private_key: str = ""
    contract_address: str = ""

    # thresholds
    face_cosine_threshold: float = 0.363
    phash_max_distance: int = 12
    max_candidates: int = 25

    # paths
    root: Path = PROJECT_ROOT
    """Base directory for models/, output/ and evidence/.

    Defaults to the repository root. Override with PROJECT_DIR to keep
    generated artefacts outside the source tree (and so that tests can run
    without writing into the repository).
    """

    @property
    def models_dir(self) -> Path:
        return self.root / "models"

    @property
    def output_dir(self) -> Path:
        return self.root / "output"

    @property
    def evidence_dir(self) -> Path:
        return self.root / "evidence"

    def tx_url(self, tx_hash: str) -> str:
        return f"{self.explorer_base.rstrip('/')}/tx/{tx_hash}"

    def address_url(self, address: str) -> str:
        return f"{self.explorer_base.rstrip('/')}/address/{address}"

    def require(self, *fields: str) -> None:
        """Fail fast with an actionable message if a needed field is unset."""
        missing = [f for f in fields if not getattr(self, f, "")]
        if missing:
            env_names = ", ".join(f.upper() for f in missing)
            raise ConfigError(
                f"missing required configuration: {env_names}. "
                "Copy .env.example to .env and fill these in "
                "(see README > Environment Variables)."
            )


def load_settings(dotenv_path: str | Path | None = None) -> Settings:
    """Load settings from .env plus the process environment.

    Real environment variables win over .env, which is what you want when
    overriding a single value for one run.
    """
    try:
        from dotenv import load_dotenv

        load_dotenv(dotenv_path or (PROJECT_ROOT / ".env"), override=False)
    except ImportError:
        # python-dotenv is optional; plain environment variables still work.
        pass

    return Settings(
        search_provider=_env("SEARCH_PROVIDER", "serpapi_lens").lower(),
        serpapi_key=_env("SERPAPI_KEY"),
        tineye_api_key=_env("TINEYE_API_KEY"),
        fixture_path=_env("FIXTURE_PATH"),
        publish_provider=_env("PUBLISH_PROVIDER", "catbox").lower(),
        imgbb_api_key=_env("IMGBB_API_KEY"),
        chain_name=_env("CHAIN_NAME", "base-sepolia"),
        chain_id=_env_int("CHAIN_ID", 84532),
        rpc_url=_env("RPC_URL", "https://sepolia.base.org"),
        explorer_base=_env("EXPLORER_BASE", "https://sepolia.basescan.org"),
        private_key=_env("PRIVATE_KEY"),
        contract_address=_env("CONTRACT_ADDRESS"),
        face_cosine_threshold=_env_float("FACE_COSINE_THRESHOLD", 0.363),
        phash_max_distance=_env_int("PHASH_MAX_DISTANCE", 12),
        max_candidates=_env_int("MAX_CANDIDATES", 25),
        root=Path(_env("PROJECT_DIR")).expanduser().resolve() if _env("PROJECT_DIR") else PROJECT_ROOT,
    )
