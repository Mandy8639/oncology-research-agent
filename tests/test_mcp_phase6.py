"""Phase 6: MCP tool functions respond (stdio server import smoke)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oncology_research_agent.corpus.seed import seed_corpus


@pytest.fixture()
def seeded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "corpus.db"
    seed_corpus(db, force=True)
    monkeypatch.setenv("ONCO_DB_PATH", str(db))
    return db


def test_mcp_tools_respond(seeded: Path) -> None:
    import importlib.util
    import sys

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    spec = importlib.util.spec_from_file_location("mcp_server", root / "mcp_server.py")
    assert spec and spec.loader
    mcp_server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mcp_server)

    hits = json.loads(mcp_server.search_corpus("ONC-101", limit=20))
    assert isinstance(hits, list)
    assert len(hits) >= 1

    src = json.loads(mcp_server.get_source("ONC-101"))
    assert src["id"] == "ONC-101"
    assert src["kind"] == "drug"

    proposed = json.loads(
        mcp_server.propose_answer(
            "MCP-1",
            "What is the molecular target of synthetic compound ONC-101?",
            "grounded",
        )
    )
    assert proposed["guardrail"]["decision"] in {"ALLOW", "HOLD", "BLOCK"}
    assert proposed["cost_usd"] == 0.0
