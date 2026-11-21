"""Phase 4: review queue end-to-end + forced breach pauses the agent."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from oncology_research_agent.agent.loop import run_agent
from oncology_research_agent.controls.digest import alert_and_pause_if_needed, clear_pause
from oncology_research_agent.corpus.governed import GovernedCorpus
from oncology_research_agent.corpus.seed import seed_corpus
from oncology_research_agent.review.queue import approve, list_held


@pytest.fixture()
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> GovernedCorpus:
    db = tmp_path / "corpus.db"
    seed_corpus(db, force=True)
    monkeypatch.setenv("ONCO_DB_PATH", str(db))
    return GovernedCorpus(db)


def test_approve_held_lands_in_memory(corpus: GovernedCorpus) -> None:
    out = run_agent(
        corpus,
        question_id="P4-HOLD",
        question="PAP-001 and PAP-002 disagree on SYN-MKI67 — resolve.",
        scenario="conflict",
    )
    assert out["guardrail"]["decision"] == "HOLD"
    held = list_held(corpus)
    assert any(h["id"] == "P4-HOLD" for h in held)

    approved = approve(
        corpus,
        "P4-HOLD",
        reason="Scientist accepts both citations with caveat",
        actor="dr_demo",
    )
    assert approved["status"] == "approved"
    mem = corpus.recall_memory(50)
    assert any(m["kind"] == "human_feedback" and "APPROVE" in m["content"] for m in mem)


def test_forced_breach_pauses_agent(corpus: GovernedCorpus) -> None:
    for i in range(90):
        corpus.append_answer(
            question_id=f"A-{i}",
            proposed_answer="ok",
            guardrail_verdict="ALLOW",
            final_answer="ok",
            actor="agent",
            reason="fully_grounded",
            citations=["ONC-101"],
        )
    digest = alert_and_pause_if_needed(corpus)
    assert digest["paused"] is True
    assert "auto_allow_rate_breach" in (digest.get("breaches") or []) or digest.get("alert")

    blocked = run_agent(
        corpus,
        question_id="P4-PAUSED",
        question="What is ONC-101 target?",
        scenario="grounded",
    )
    assert blocked["final_status"] == "paused"

    clear_pause(corpus, reason="rates reviewed", actor="dr_demo")
    assert corpus.is_paused() is False


def test_api_endpoints(corpus: GovernedCorpus, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONCO_DB_PATH", str(corpus.path))
    from oncology_research_agent.api.app import app

    client = TestClient(app)
    assert client.get("/api/health").json()["status"] == "ok"
    run_agent(
        corpus,
        question_id="API-HOLD",
        question="Conflicting sources PAP-001 and PAP-002 disagree",
        scenario="conflict",
    )
    qs = client.get("/questions").json()
    assert any(q["id"] == "API-HOLD" for q in qs)
    digest = client.get("/controls/digest").json()
    assert "auto_allow_rate" in digest
    # evals may or may not exist in tmp — just ensure route shape
    # seed a tiny report
    from oncology_research_agent.config import PROJECT_ROOT

    reports = PROJECT_ROOT / "evals" / "reports"
    if (reports / "latest-stub.json").exists():
        ev = client.get("/evals/latest").json()
        assert "metrics" in ev
