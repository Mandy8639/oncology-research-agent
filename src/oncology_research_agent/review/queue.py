"""Human review queue: approve/reject held answers → audit log + memory feedback."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from oncology_research_agent.corpus.governed import GovernedCorpus


def list_held(corpus: GovernedCorpus) -> list[dict[str, Any]]:
    return corpus.list_questions(status="held")


def approve(
    corpus: GovernedCorpus,
    question_id: str,
    *,
    reason: str,
    actor: str = "reviewing_scientist",
) -> dict[str, Any]:
    q = corpus.get_question(question_id)
    if q is None:
        raise KeyError(f"Unknown question {question_id}")
    if q.get("status") != "held":
        raise ValueError(f"Question {question_id} is not held (status={q.get('status')})")
    if not reason.strip():
        raise ValueError("Human reason is required")

    final = q.get("proposed_answer") or ""
    corpus.append_answer(
        question_id=question_id,
        proposed_answer=q.get("proposed_answer") or "",
        guardrail_verdict="ALLOW",
        final_answer=final,
        actor=actor,
        reason=f"human_approve: {reason}",
        citations=list(q.get("citations") or []),
    )
    corpus.append_memory(
        kind="human_feedback",
        content=f"APPROVE: {reason}",
        source=f"review:{question_id}",
        question_id=question_id,
    )
    corpus.upsert_question(
        {
            "id": question_id,
            "text": q["text"],
            "status": "approved",
            "proposed_answer": q.get("proposed_answer"),
            "guardrail_decision": "ALLOW",
            "guardrail_reason": f"human_approve: {reason}",
            "citations": q.get("citations") or [],
            "final_verdict": q.get("final_verdict") or "GROUNDED",
            "final_answer": final,
        }
    )
    return corpus.get_question(question_id) or {}


def reject(
    corpus: GovernedCorpus,
    question_id: str,
    *,
    reason: str,
    actor: str = "reviewing_scientist",
) -> dict[str, Any]:
    q = corpus.get_question(question_id)
    if q is None:
        raise KeyError(f"Unknown question {question_id}")
    if q.get("status") != "held":
        raise ValueError(f"Question {question_id} is not held (status={q.get('status')})")
    if not reason.strip():
        raise ValueError("Human reason is required")

    corpus.append_answer(
        question_id=question_id,
        proposed_answer=q.get("proposed_answer") or "",
        guardrail_verdict="BLOCK",
        final_answer=None,
        actor=actor,
        reason=f"human_reject: {reason}",
        citations=list(q.get("citations") or []),
    )
    corpus.append_memory(
        kind="human_feedback",
        content=f"REJECT: {reason}",
        source=f"review:{question_id}",
        question_id=question_id,
    )
    corpus.upsert_question(
        {
            "id": question_id,
            "text": q["text"],
            "status": "rejected",
            "proposed_answer": q.get("proposed_answer"),
            "guardrail_decision": "BLOCK",
            "guardrail_reason": f"human_reject: {reason}",
            "citations": q.get("citations") or [],
            "final_verdict": q.get("final_verdict"),
            "final_answer": None,
        }
    )
    return corpus.get_question(question_id) or {}


def due_by_iso(hours: int = 24) -> str:
    from datetime import timedelta

    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat()
