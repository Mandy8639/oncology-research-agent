"""Detective controls digest and pause clear."""

from __future__ import annotations

from typing import Any

from oncology_research_agent.config import (
    AUTO_ALLOW_RATE_THRESHOLD,
    UNGROUNDED_RATE_THRESHOLD,
)
from oncology_research_agent.corpus.governed import GovernedCorpus
from oncology_research_agent.guardrail.pause import PauseChecker


def compute_digest(corpus: GovernedCorpus) -> dict[str, Any]:
    answers = corpus.list_recent_answers(100)
    n = len(answers)
    by_verdict: dict[str, int] = {"ALLOW": 0, "HOLD": 0, "BLOCK": 0}
    ungrounded = 0
    fabrication_attempts = 0
    for a in answers:
        v = a.get("guardrail_verdict") or ""
        if v in by_verdict:
            by_verdict[v] += 1
        reason = str(a.get("reason") or "")
        if "ungrounded" in reason or v == "PARTIAL":
            ungrounded += 1
        if "invented_citation" in reason:
            fabrication_attempts += 1

    allow_rate = (by_verdict["ALLOW"] / n) if n else 0.0
    hold_rate = (by_verdict["HOLD"] / n) if n else 0.0
    ungrounded_rate = (ungrounded / n) if n else 0.0
    exceptions = corpus.list_exceptions(200)
    freshness = corpus.freshness_check()
    paused = corpus.is_paused()
    pause_reason = corpus.get_control("pause_reason") or ""

    breaches: list[str] = []
    if not freshness.ok:
        breaches.append(f"freshness:{freshness.reason}")
    if n >= 10 and ungrounded_rate > UNGROUNDED_RATE_THRESHOLD:
        breaches.append("ungrounded_rate_breach")
    if n >= 10 and allow_rate > AUTO_ALLOW_RATE_THRESHOLD:
        breaches.append("auto_allow_rate_breach")

    return {
        "questions_answered": n,
        "counts_by_verdict": by_verdict,
        "hold_rate": round(hold_rate, 4),
        "auto_allow_rate": round(allow_rate, 4),
        "ungrounded_claim_rate": round(ungrounded_rate, 4),
        "fabrication_attempts": fabrication_attempts,
        "exceptions_inventory_size": len(exceptions),
        "breaches": breaches,
        "paused": paused,
        "pause_reason": pause_reason,
        "freshness": {
            "ok": freshness.ok,
            "reason": freshness.reason,
            "updated_at": freshness.updated_at,
            "version": freshness.actual_version,
        },
        "thresholds": {
            "ungrounded_claim_rate": UNGROUNDED_RATE_THRESHOLD,
            "auto_allow_rate": AUTO_ALLOW_RATE_THRESHOLD,
        },
    }


def alert_and_pause_if_needed(corpus: GovernedCorpus) -> dict[str, Any]:
    digest = compute_digest(corpus)
    checker = PauseChecker(corpus)
    pause = checker.check()
    if pause.should_pause:
        checker.apply_if_needed(pause)
        digest = compute_digest(corpus)
        digest["alert"] = {
            "level": "pause",
            "reason_code": pause.reason_code,
            "detail": pause.detail,
        }
    else:
        digest["alert"] = None
    return digest


def clear_pause(corpus: GovernedCorpus, *, reason: str, actor: str) -> dict[str, Any]:
    if not reason.strip():
        raise ValueError("Reason required to clear pause")
    corpus.set_paused(False, "")
    corpus.append_memory(
        kind="human_feedback",
        content=f"CLEAR_PAUSE: {reason}",
        source=f"controls:{actor}",
    )
    corpus.append_exception(
        reason_code="pause_cleared",
        detail=f"{actor}: {reason}",
    )
    return compute_digest(corpus)
