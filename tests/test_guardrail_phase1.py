"""Phase 1: guardrail unit tests for every mandate rule — must be 100% passing."""

from __future__ import annotations

from pathlib import Path

import pytest

from oncology_research_agent.corpus.governed import GovernedCorpus
from oncology_research_agent.corpus.seed import seed_corpus
from oncology_research_agent.guardrail.pause import PauseChecker
from oncology_research_agent.guardrail.policy import (
    Claim,
    Decision,
    GuardrailInput,
    evaluate_proposal,
)


@pytest.fixture()
def corpus(tmp_path: Path) -> GovernedCorpus:
    db = tmp_path / "corpus.db"
    seed_corpus(db, force=True)
    return GovernedCorpus(db)


def _inp(**kwargs: object) -> GuardrailInput:
    base = {
        "question_id": "Q-TEST",
        "question_text": "What does ONC-101 target?",
        "proposed_answer": "ONC-101 modulates SYN-EGFR in synthetic cohort A.",
        "claims": [
            Claim(
                text="ONC-101 modulates SYN-EGFR",
                source_ids=["ONC-101"],
            )
        ],
        "answer_verdict": "GROUNDED",
        "confidence": 0.95,
    }
    base.update(kwargs)
    return GuardrailInput(**base)  # type: ignore[arg-type]


def test_allow_fully_grounded(corpus: GovernedCorpus) -> None:
    d = evaluate_proposal(_inp(), corpus)
    assert d.decision == Decision.ALLOW
    assert d.reason_code == "fully_grounded"


def test_block_invented_citation(corpus: GovernedCorpus) -> None:
    d = evaluate_proposal(
        _inp(
            claims=[Claim(text="fake claim", source_ids=["PAP-999"])],
        ),
        corpus,
    )
    assert d.decision == Decision.BLOCK
    assert d.reason_code == "invented_citation"
    assert "PAP-999" in d.invalid_citations


def test_block_bad_quote(corpus: GovernedCorpus) -> None:
    d = evaluate_proposal(
        _inp(
            claims=[
                Claim(
                    text="quote claim",
                    source_ids=["PAP-001"],
                    quote="this quote does not exist anywhere in the source xyzzy",
                )
            ],
        ),
        corpus,
    )
    assert d.decision == Decision.BLOCK
    assert d.reason_code == "invented_citation"


def test_block_treatment_recommendation(corpus: GovernedCorpus) -> None:
    d = evaluate_proposal(
        _inp(
            question_text="What treatment should this patient receive?",
            proposed_answer="I recommend starting the patient on ONC-101 therapy.",
            claims=[],
            answer_verdict="GROUNDED",
        ),
        corpus,
    )
    assert d.decision == Decision.BLOCK
    assert d.reason_code == "treatment_recommendation"


def test_block_ungrounded_claims(corpus: GovernedCorpus) -> None:
    d = evaluate_proposal(
        _inp(
            claims=[Claim(text="unsupported statistic of 99% cure", source_ids=[])],
            answer_verdict="GROUNDED",
        ),
        corpus,
    )
    assert d.decision == Decision.BLOCK
    assert d.reason_code == "ungrounded_claims"


def test_block_real_world_claim(corpus: GovernedCorpus) -> None:
    d = evaluate_proposal(
        _inp(
            proposed_answer="This FDA-approved real-world drug cures patients.",
            claims=[Claim(text="FDA-approved real-world drug", source_ids=["ONC-101"])],
        ),
        corpus,
    )
    assert d.decision == Decision.BLOCK
    assert d.reason_code == "real_world_claim"


def test_hold_partial_grounding(corpus: GovernedCorpus) -> None:
    d = evaluate_proposal(
        _inp(
            claims=[
                Claim(text="grounded", source_ids=["ONC-101"]),
                Claim(text="not grounded", source_ids=[]),
            ],
            answer_verdict="PARTIAL",
        ),
        corpus,
    )
    assert d.decision == Decision.HOLD
    assert d.reason_code == "partial_grounding"


def test_hold_conflicting_sources(corpus: GovernedCorpus) -> None:
    d = evaluate_proposal(
        _inp(
            conflicting_sources=["PAP-001", "PAP-002"],
            claims=[
                Claim(text="a", source_ids=["PAP-001"]),
                Claim(text="b", source_ids=["PAP-002"]),
            ],
        ),
        corpus,
    )
    assert d.decision == Decision.HOLD
    assert d.reason_code == "conflicting_sources"


def test_hold_low_confidence(corpus: GovernedCorpus) -> None:
    d = evaluate_proposal(_inp(confidence=0.4), corpus)
    assert d.decision == Decision.HOLD
    assert d.reason_code == "low_confidence"


def test_hold_ambiguous(corpus: GovernedCorpus) -> None:
    d = evaluate_proposal(_inp(metadata={"ambiguous": True}), corpus)
    assert d.decision == Decision.HOLD
    assert d.reason_code == "ambiguous_question"


def test_allow_abstain(corpus: GovernedCorpus) -> None:
    d = evaluate_proposal(
        _inp(
            proposed_answer="I abstain — outside corpus scope.",
            claims=[],
            answer_verdict="ABSTAIN",
            abstain_reason="outside_corpus",
        ),
        corpus,
    )
    assert d.decision == Decision.ALLOW
    assert d.reason_code.startswith("abstain:")


def test_pause_on_stale_corpus(corpus: GovernedCorpus) -> None:
    # Force stale updated_at
    with corpus._conn() as conn:
        conn.execute("UPDATE meta SET value = '2020-01-01T00:00:00+00:00' WHERE key = 'updated_at'")
        conn.commit()
    result = PauseChecker(corpus).check(recent_answers=[])
    assert result.should_pause is True
    assert result.reason_code == "corpus_freshness_failed"


def test_pause_on_fabrication_streak(corpus: GovernedCorpus) -> None:
    answers = [
        {
            "guardrail_verdict": "BLOCK",
            "reason": "invented_citation: PAP-999",
            "citations": "[]",
        },
        {
            "guardrail_verdict": "BLOCK",
            "reason": "invented_citation: PAP-998",
            "citations": "[]",
        },
    ]
    result = PauseChecker(corpus).check(recent_answers=answers)
    assert result.should_pause is True
    assert result.reason_code == "fabrication_streak"


def test_pause_on_block_streak(corpus: GovernedCorpus) -> None:
    answers = [
        {"guardrail_verdict": "BLOCK", "reason": "treatment_recommendation", "citations": "[]"},
        {"guardrail_verdict": "BLOCK", "reason": "treatment_recommendation", "citations": "[]"},
        {"guardrail_verdict": "BLOCK", "reason": "ungrounded_claims", "citations": "[]"},
    ]
    result = PauseChecker(corpus).check(recent_answers=answers)
    assert result.should_pause is True
    assert result.reason_code in ("block_streak", "fabrication_streak")


def test_pause_on_auto_allow_breach(corpus: GovernedCorpus) -> None:
    answers = [
        {"guardrail_verdict": "ALLOW", "reason": "fully_grounded", "citations": '["ONC-101"]'}
        for _ in range(90)
    ] + [
        {"guardrail_verdict": "HOLD", "reason": "partial_grounding", "citations": "[]"}
        for _ in range(10)
    ]
    result = PauseChecker(corpus).check(recent_answers=answers)
    assert result.should_pause is True
    assert result.reason_code == "auto_allow_rate_breach"


def test_pause_on_ungrounded_rate_breach(corpus: GovernedCorpus) -> None:
    answers = [
        {"guardrail_verdict": "HOLD", "reason": "ungrounded partial", "citations": "[]"}
        for _ in range(20)
    ]
    result = PauseChecker(corpus).check(recent_answers=answers)
    assert result.should_pause is True
    assert result.reason_code == "ungrounded_rate_breach"
