"""Deterministic guardrail: ALLOW / HOLD / BLOCK — no LLM calls."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from oncology_research_agent.config import GROUNDING_CONFIDENCE_THRESHOLD
from oncology_research_agent.corpus.governed import GovernedCorpus

# Patterns that indicate treatment-adjacent / out-of-mandate content.
TREATMENT_PATTERNS = [
    re.compile(r"\btreat(ment|ing)?\b.*\bpatient\b", re.I),
    re.compile(r"\bpatient\b.*\b(should|must|recommend)\b", re.I),
    re.compile(r"\brecommend(ed|ation)?\b.*\b(dose|therapy|regimen)\b", re.I),
    re.compile(r"\bprescrib(e|ed|ing)\b", re.I),
    re.compile(r"\bfor (this|the) patient\b", re.I),
    re.compile(r"\bstart (the )?patient on\b", re.I),
]

REAL_WORLD_CLAIM_PATTERNS = [
    re.compile(r"\bFDA[- ]approved\b", re.I),
    re.compile(r"\breal[- ]world (patient|trial|drug)\b", re.I),
]


class Decision(StrEnum):
    ALLOW = "ALLOW"
    HOLD = "HOLD"
    BLOCK = "BLOCK"


class Verdict(StrEnum):
    GROUNDED = "GROUNDED"
    PARTIAL = "PARTIAL"
    ABSTAIN = "ABSTAIN"


@dataclass
class Claim:
    text: str
    source_ids: list[str] = field(default_factory=list)
    quote: str | None = None


@dataclass
class GuardrailInput:
    question_id: str
    question_text: str
    proposed_answer: str
    claims: list[Claim]
    answer_verdict: str  # GROUNDED | PARTIAL | ABSTAIN
    confidence: float = 1.0
    conflicting_sources: list[str] = field(default_factory=list)
    abstain_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GuardrailDecision:
    decision: Decision
    reason_code: str
    detail: str
    answer_verdict: str
    grounded_claim_count: int
    ungrounded_claim_count: int
    invalid_citations: list[str] = field(default_factory=list)


def _answer_blob(inp: GuardrailInput) -> str:
    """Scan proposed answer + claims only (not the question) for out-of-mandate content."""
    parts = [inp.proposed_answer]
    parts.extend(c.text for c in inp.claims)
    return "\n".join(parts)


def _is_treatment_adjacent(text: str) -> bool:
    return any(p.search(text) for p in TREATMENT_PATTERNS)


def _has_real_world_claim(text: str) -> bool:
    return any(p.search(text) for p in REAL_WORLD_CLAIM_PATTERNS)


def evaluate_proposal(
    inp: GuardrailInput,
    corpus: GovernedCorpus,
) -> GuardrailDecision:
    """Evaluate a proposed answer against the mandate. Deterministic."""
    # ABSTAIN may go out immediately — never guess; no BLOCK for asking about OOD topics
    if inp.answer_verdict == Verdict.ABSTAIN.value:
        reason = inp.abstain_reason or "outside_corpus"
        return GuardrailDecision(
            decision=Decision.ALLOW,
            reason_code=f"abstain:{reason}",
            detail="Abstention within mandate; may go out with a reason.",
            answer_verdict=Verdict.ABSTAIN.value,
            grounded_claim_count=0,
            ungrounded_claim_count=0,
        )

    blob = _answer_blob(inp)

    # BLOCK: treatment recommendation for a (real) patient
    if _is_treatment_adjacent(blob):
        return GuardrailDecision(
            decision=Decision.BLOCK,
            reason_code="treatment_recommendation",
            detail="Proposed content includes a treatment recommendation; always BLOCK.",
            answer_verdict=inp.answer_verdict,
            grounded_claim_count=0,
            ungrounded_claim_count=len(inp.claims),
        )

    if _has_real_world_claim(blob):
        return GuardrailDecision(
            decision=Decision.BLOCK,
            reason_code="real_world_claim",
            detail="Claim about real-world drug/trial/patient outside synthetic corpus.",
            answer_verdict=inp.answer_verdict,
            grounded_claim_count=0,
            ungrounded_claim_count=len(inp.claims),
        )

    invalid_citations: list[str] = []
    grounded = 0
    ungrounded = 0

    for claim in inp.claims:
        if not claim.source_ids:
            ungrounded += 1
            continue
        claim_ok = True
        for sid in claim.source_ids:
            if not corpus.source_exists(sid):
                invalid_citations.append(sid)
                claim_ok = False
            elif claim.quote and not corpus.quote_supported(sid, claim.quote):
                invalid_citations.append(f"{sid}:bad_quote")
                claim_ok = False
        if claim_ok:
            grounded += 1
        else:
            ungrounded += 1

    # BLOCK: invented citation
    if invalid_citations:
        return GuardrailDecision(
            decision=Decision.BLOCK,
            reason_code="invented_citation",
            detail=f"Invented or unsupported citations: {invalid_citations}",
            answer_verdict=inp.answer_verdict,
            grounded_claim_count=grounded,
            ungrounded_claim_count=ungrounded,
            invalid_citations=invalid_citations,
        )

    # HOLD: conflicting sources
    if inp.conflicting_sources or inp.metadata.get("must_hold"):
        return GuardrailDecision(
            decision=Decision.HOLD,
            reason_code="conflicting_sources",
            detail=f"Conflicting corpus sources: {inp.conflicting_sources}",
            answer_verdict=inp.answer_verdict,
            grounded_claim_count=grounded,
            ungrounded_claim_count=ungrounded,
        )

    # HOLD: ambiguous / low confidence
    if inp.confidence < GROUNDING_CONFIDENCE_THRESHOLD:
        return GuardrailDecision(
            decision=Decision.HOLD,
            reason_code="low_confidence",
            detail=f"Grounding confidence {inp.confidence} below threshold.",
            answer_verdict=inp.answer_verdict,
            grounded_claim_count=grounded,
            ungrounded_claim_count=ungrounded,
        )

    # HOLD / PARTIAL: some claims ungrounded
    if inp.answer_verdict == Verdict.PARTIAL.value or (ungrounded > 0 and grounded > 0):
        return GuardrailDecision(
            decision=Decision.HOLD,
            reason_code="partial_grounding",
            detail="Some claims grounded, some not — HOLD for reviewing scientist.",
            answer_verdict=Verdict.PARTIAL.value,
            grounded_claim_count=grounded,
            ungrounded_claim_count=ungrounded,
        )

    # BLOCK-ish path for fully ungrounded non-abstain answers presented as fact
    if grounded == 0 and ungrounded > 0:
        return GuardrailDecision(
            decision=Decision.BLOCK,
            reason_code="ungrounded_claims",
            detail="Factual claims with no grounding sources.",
            answer_verdict=inp.answer_verdict,
            grounded_claim_count=0,
            ungrounded_claim_count=ungrounded,
        )

    # Ambiguous question flag
    if inp.metadata.get("ambiguous"):
        return GuardrailDecision(
            decision=Decision.HOLD,
            reason_code="ambiguous_question",
            detail="Question flagged as ambiguous.",
            answer_verdict=inp.answer_verdict,
            grounded_claim_count=grounded,
            ungrounded_claim_count=ungrounded,
        )

    # ALLOW: all claims grounded
    if grounded > 0 and ungrounded == 0:
        return GuardrailDecision(
            decision=Decision.ALLOW,
            reason_code="fully_grounded",
            detail="All factual claims cite valid corpus sources.",
            answer_verdict=Verdict.GROUNDED.value,
            grounded_claim_count=grounded,
            ungrounded_claim_count=0,
        )

    # Empty claims with GROUNDED verdict — treat as HOLD (suspicious)
    return GuardrailDecision(
        decision=Decision.HOLD,
        reason_code="empty_claims",
        detail="No claims provided for a non-abstain answer.",
        answer_verdict=inp.answer_verdict,
        grounded_claim_count=0,
        ungrounded_claim_count=0,
    )
