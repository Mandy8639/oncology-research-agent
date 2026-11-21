"""Phase 0 checks: schema, deterministic seed, freshness, contamination safeguard."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oncology_research_agent.corpus.governed import GovernedCorpus
from oncology_research_agent.corpus.seed import seed_corpus


@pytest.fixture()
def seeded_db(tmp_path: Path) -> Path:
    db = tmp_path / "corpus.db"
    seed_corpus(db, force=True)
    return db


def test_seed_row_counts(seeded_db: Path) -> None:
    corpus = GovernedCorpus(seeded_db)
    counts = corpus.counts()
    assert counts["papers"] == 120
    assert counts["trials"] == 60
    assert counts["drugs"] == 40
    assert counts["mechanisms"] == 25


def test_reseed_reproduces_identical_counts(tmp_path: Path) -> None:
    db_a = tmp_path / "a.db"
    db_b = tmp_path / "b.db"
    a = seed_corpus(db_a, force=True)
    b = seed_corpus(db_b, force=True)
    assert a["papers"] == b["papers"] == 120
    assert a["trials"] == b["trials"] == 60
    assert a["drugs"] == b["drugs"] == 40
    assert a["mechanisms"] == b["mechanisms"] == 25

    corpus_a = GovernedCorpus(db_a)
    corpus_b = GovernedCorpus(db_b)
    assert corpus_a.all_source_ids() == corpus_b.all_source_ids()
    paper_a = corpus_a.get_source("PAP-001")
    paper_b = corpus_b.get_source("PAP-001")
    assert paper_a is not None and paper_b is not None
    assert paper_a.payload["title"] == paper_b.payload["title"]


def test_freshness_ok_after_seed(seeded_db: Path) -> None:
    corpus = GovernedCorpus(seeded_db)
    result = corpus.freshness_check()
    assert result.ok is True
    assert result.reason == "ok"


def test_all_entities_labelled_synthetic(seeded_db: Path) -> None:
    corpus = GovernedCorpus(seeded_db)
    for sid in list(corpus.all_source_ids())[:20]:
        src = corpus.get_source(sid)
        assert src is not None
        assert src.payload.get("synthetic_label") == "SYNTHETIC"


def test_golden_question_text_not_in_corpus(seeded_db: Path, tmp_path: Path) -> None:
    """Contamination safeguard: golden question text must not appear in corpus."""
    golden_path = Path(__file__).resolve().parents[1] / "evals" / "golden_questions.json"
    if golden_path.exists():
        questions = json.loads(golden_path.read_text())
        forbidden = [q["question"] for q in questions]
    else:
        # Phase 0 runs before golden set exists — use sentinel phrases.
        forbidden = [
            "GOLDEN_EVAL_SENTINEL_PHRASE_SHOULD_NEVER_APPEAR_IN_CORPUS_XYZ",
            "What is the exact progression-free survival for REAL_DRUG_NOT_IN_CORPUS?",
        ]
    corpus = GovernedCorpus(seeded_db)
    hits = corpus.assert_no_contamination(forbidden)
    assert hits == []


def test_search_and_get_source(seeded_db: Path) -> None:
    corpus = GovernedCorpus(seeded_db)
    src = corpus.get_source("ONC-101")
    assert src is not None
    assert src.kind == "drug"
    results = corpus.search("SYN-EGFR", limit=5)
    assert len(results) >= 1
