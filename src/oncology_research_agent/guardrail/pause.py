"""Pause-condition detective controls — deterministic."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from oncology_research_agent.config import (
    AUTO_ALLOW_RATE_THRESHOLD,
    BLOCK_STREAK_PAUSE,
    FABRICATION_STREAK_PAUSE,
    UNGROUNDED_RATE_THRESHOLD,
)
from oncology_research_agent.corpus.governed import GovernedCorpus
from oncology_research_agent.guardrail.policy import Decision


@dataclass
class PauseResult:
    should_pause: bool
    reason_code: str | None
    detail: str


class PauseChecker:
    """Evaluate pause conditions against recent answers + corpus freshness."""

    def __init__(self, corpus: GovernedCorpus) -> None:
        self.corpus = corpus

    def check(
        self,
        *,
        recent_decisions: list[str] | None = None,
        recent_answers: list[dict[str, Any]] | None = None,
    ) -> PauseResult:
        freshness = self.corpus.freshness_check()
        if not freshness.ok:
            return PauseResult(
                should_pause=True,
                reason_code="corpus_freshness_failed",
                detail=f"Freshness check failed: {freshness.reason}",
            )

        answers = (
            recent_answers if recent_answers is not None else self.corpus.list_recent_answers(100)
        )
        decisions = recent_decisions
        if decisions is None:
            decisions = [a.get("guardrail_verdict", "") for a in answers]

        # Two citation-fabrication BLOCKs in a row
        fab_streak = 0
        for d in decisions[:FABRICATION_STREAK_PAUSE]:
            # decisions may be reason codes or ALLOW/HOLD/BLOCK
            if d in ("BLOCK", "invented_citation") or str(d).startswith("BLOCK"):
                # Need reason — look at answer reason field when available
                fab_streak += 1
            else:
                break
        # More precise: scan answers for invented_citation
        fab_row = 0
        for a in answers[:FABRICATION_STREAK_PAUSE]:
            reason = str(a.get("reason", ""))
            verdict = str(a.get("guardrail_verdict", ""))
            if verdict == Decision.BLOCK.value and "invented_citation" in reason:
                fab_row += 1
            else:
                break
        if fab_row >= FABRICATION_STREAK_PAUSE:
            return PauseResult(
                should_pause=True,
                reason_code="fabrication_streak",
                detail=f"{fab_row} consecutive citation-fabrication BLOCKs",
            )

        # Three consecutive guardrail BLOCKs
        block_streak = 0
        for a in answers[:BLOCK_STREAK_PAUSE]:
            if a.get("guardrail_verdict") == Decision.BLOCK.value:
                block_streak += 1
            else:
                break
        if block_streak >= BLOCK_STREAK_PAUSE:
            return PauseResult(
                should_pause=True,
                reason_code="block_streak",
                detail=f"{block_streak} consecutive guardrail BLOCKs",
            )

        if len(answers) >= 10:
            ungrounded = 0
            allows = 0
            for a in answers[:100]:
                reason = str(a.get("reason", ""))
                verdict = str(a.get("guardrail_verdict", ""))
                if "ungrounded" in reason or verdict == "PARTIAL":
                    ungrounded += 1
                # Also count claims from citations emptiness
                cites = a.get("citations") or "[]"
                if isinstance(cites, str):
                    try:
                        cites = json.loads(cites)
                    except json.JSONDecodeError:
                        cites = []
                if verdict == Decision.ALLOW.value:
                    allows += 1
            n = min(len(answers), 100)
            ungrounded_rate = ungrounded / n
            auto_allow_rate = allows / n
            if ungrounded_rate > UNGROUNDED_RATE_THRESHOLD:
                return PauseResult(
                    should_pause=True,
                    reason_code="ungrounded_rate_breach",
                    detail=f"Ungrounded-claim rate {ungrounded_rate:.2%} > 5%",
                )
            if auto_allow_rate > AUTO_ALLOW_RATE_THRESHOLD:
                return PauseResult(
                    should_pause=True,
                    reason_code="auto_allow_rate_breach",
                    detail=f"Auto-allow rate {auto_allow_rate:.2%} > 80%",
                )

        return PauseResult(should_pause=False, reason_code=None, detail="ok")

    def apply_if_needed(self, result: PauseResult, question_id: str | None = None) -> None:
        if not result.should_pause:
            return
        self.corpus.set_paused(True, reason=result.reason_code or "pause")
        self.corpus.append_exception(
            reason_code=result.reason_code or "pause",
            detail=result.detail,
            question_id=question_id,
        )
