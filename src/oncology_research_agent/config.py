"""Runtime configuration from environment."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "corpus.db"
CORPUS_VERSION = "1.0.0"
CORPUS_SEED = 42
FRESHNESS_MAX_AGE_HOURS = 24
GROUNDING_CONFIDENCE_THRESHOLD = 0.7
UNGROUNDED_RATE_THRESHOLD = 0.05
AUTO_ALLOW_RATE_THRESHOLD = 0.80
FABRICATION_STREAK_PAUSE = 2
BLOCK_STREAK_PAUSE = 3
DAILY_SPEND_CAP_USD = 1.00
DEFAULT_MODEL = "claude-haiku-4-5"


def db_path() -> Path:
    raw = os.environ.get("ONCO_DB_PATH")
    if raw:
        p = Path(raw)
        return p if p.is_absolute() else PROJECT_ROOT / p
    return DEFAULT_DB_PATH


def corpus_version() -> str:
    return os.environ.get("ONCO_CORPUS_VERSION", CORPUS_VERSION)


def mode() -> str:
    return os.environ.get("ONCO_MODE", "stub").lower()


def model_name() -> str:
    return os.environ.get("ONCO_MODEL", DEFAULT_MODEL)


def daily_spend_cap_usd() -> float:
    return float(os.environ.get("ONCO_DAILY_SPEND_CAP_USD", str(DAILY_SPEND_CAP_USD)))


def anthropic_api_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY") or None
