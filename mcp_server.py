#!/usr/bin/env python3
"""MCP server exposing governed oncology-research-agent tools over stdio."""

from __future__ import annotations

import json

from mcp.server.mcpserver import MCPServer

from oncology_research_agent.agent.loop import run_agent
from oncology_research_agent.config import db_path
from oncology_research_agent.corpus.governed import GovernedCorpus
from oncology_research_agent.corpus.seed import refresh_updated_at, seed_corpus
from oncology_research_agent.review.queue import approve

mcp = MCPServer("oncology-research-agent")


def _corpus() -> GovernedCorpus:
    path = db_path()
    if not path.exists():
        seed_corpus(path, force=True)
        refresh_updated_at(path)
    return GovernedCorpus(path)


@mcp.tool()
def search_corpus(query: str, limit: int = 8) -> str:
    """Search the governed synthetic corpus (papers, trials, drugs, mechanisms)."""
    hits = _corpus().search(query, limit=limit)
    payload = [
        {
            "id": h.id,
            "kind": h.kind,
            "summary": {
                k: h.payload.get(k)
                for k in (
                    "title",
                    "mechanism",
                    "molecular_target",
                    "indication",
                    "pathway",
                    "primary_endpoint",
                )
                if k in h.payload
            },
        }
        for h in hits
    ]
    return json.dumps(payload, indent=2)


@mcp.tool()
def get_source(source_id: str) -> str:
    """Fetch one corpus source by ID (PAP-/TRL-/ONC-/MEC-)."""
    src = _corpus().get_source(source_id)
    if src is None:
        return json.dumps({"error": "not_found", "id": source_id})
    return json.dumps({"id": src.id, "kind": src.kind, "payload": src.payload}, indent=2)


@mcp.tool()
def propose_answer(question_id: str, question: str, scenario: str = "") -> str:
    """Run the bounded agent loop (retrieve → propose → guardrail)."""
    result = run_agent(
        _corpus(),
        question_id=question_id,
        question=question,
        scenario=scenario or None,
    )
    keep = {
        "question_id": result.get("question_id"),
        "final_status": result.get("final_status"),
        "final_answer": result.get("final_answer"),
        "guardrail": result.get("guardrail"),
        "citations": result.get("citations"),
        "paused": result.get("paused"),
        "cost_usd": result.get("cost_usd"),
    }
    return json.dumps(keep, indent=2)


@mcp.tool()
def submit_for_review(
    question_id: str,
    reason: str,
    actor: str = "reviewing_scientist",
) -> str:
    """Approve a held answer (human review). Reject via CLI if needed."""
    try:
        q = approve(_corpus(), question_id, reason=reason, actor=actor)
        return json.dumps(q, indent=2, default=str)
    except (KeyError, ValueError) as e:
        return json.dumps({"error": str(e)})


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
