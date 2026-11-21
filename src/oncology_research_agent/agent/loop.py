"""LangGraph agent loop: fetch → recall → retrieve → propose → guardrail → answer/hold."""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from oncology_research_agent.agent.llm import propose_answer
from oncology_research_agent.corpus.governed import GovernedCorpus
from oncology_research_agent.guardrail.pause import PauseChecker
from oncology_research_agent.guardrail.policy import (
    Claim,
    Decision,
    GuardrailInput,
    evaluate_proposal,
)


class AgentState(TypedDict, total=False):
    question_id: str
    question: str
    scenario: str
    memory: list[dict[str, Any]]
    retrieved: list[dict[str, Any]]
    proposed: dict[str, Any]
    guardrail: dict[str, Any]
    final_status: str
    final_answer: str | None
    paused: bool
    pause_reason: str | None
    cost_usd: float
    citations: list[str]


def _retrieval_query(question: str) -> str:
    # Prefer synthetic IDs / target tokens
    tokens = [
        t
        for t in question.replace("?", " ").replace(",", " ").split()
        if t.upper().startswith(("PAP-", "TRL-", "ONC-", "MEC-", "SYN-"))
        or t.lower() in {"nsclc", "her2", "egfr", "kras", "parp", "cdk4/6"}
    ]
    return " ".join(tokens) if tokens else question[:80]


def build_graph(corpus: GovernedCorpus):
    def fetch_question(state: AgentState) -> AgentState:
        corpus.upsert_question(
            {
                "id": state["question_id"],
                "text": state["question"],
                "status": "processing",
            }
        )
        return state

    def recall_memory(state: AgentState) -> AgentState:
        mem = corpus.recall_memory(limit=20)
        return {**state, "memory": mem}

    def retrieve(state: AgentState) -> AgentState:
        q = _retrieval_query(state["question"])
        hits = corpus.search(q, limit=8)
        # Always include any explicit IDs mentioned
        import re

        for sid in re.findall(r"\b(?:PAP|TRL|MEC)-\d{3}\b|\bONC-\d{3}\b", state["question"]):
            src = corpus.get_source(sid)
            if src and all(h.id != sid for h in hits):
                hits.insert(0, src)
        retrieved = [{"id": h.id, "kind": h.kind, "payload": h.payload} for h in hits]
        return {**state, "retrieved": retrieved}

    def propose(state: AgentState) -> AgentState:
        result = propose_answer(
            state["question"],
            state.get("retrieved") or [],
            state.get("memory") or [],
            scenario=state.get("scenario"),
        )
        proposed = {
            "answer_verdict": result.answer_verdict,
            "proposed_answer": result.proposed_answer,
            "claims": result.claims,
            "confidence": result.confidence,
            "conflicting_sources": result.conflicting_sources,
            "abstain_reason": result.abstain_reason,
            "metadata": result.metadata,
        }
        return {
            **state,
            "proposed": proposed,
            "cost_usd": state.get("cost_usd", 0.0) + result.cost_usd,
        }

    def guardrail_node(state: AgentState) -> AgentState:
        # Pause check first (freshness + streaks)
        checker = PauseChecker(corpus)
        if state.get("proposed", {}).get("metadata", {}).get("force_stale"):
            with corpus._conn() as conn:
                conn.execute(
                    "UPDATE meta SET value = '2020-01-01T00:00:00+00:00' WHERE key = 'updated_at'"
                )
                conn.commit()
        pause = checker.check()
        if corpus.is_paused() or pause.should_pause:
            if pause.should_pause:
                checker.apply_if_needed(pause, state["question_id"])
            return {
                **state,
                "paused": True,
                "pause_reason": pause.reason_code or corpus.get_control("pause_reason"),
                "final_status": "paused",
                "final_answer": None,
                "guardrail": {
                    "decision": "BLOCK",
                    "reason_code": pause.reason_code or "agent_paused",
                    "detail": pause.detail,
                },
            }

        prop = state["proposed"]
        claims = [
            Claim(
                text=c.get("text", ""),
                source_ids=list(c.get("source_ids") or []),
                quote=c.get("quote"),
            )
            for c in prop.get("claims") or []
        ]
        gin = GuardrailInput(
            question_id=state["question_id"],
            question_text=state["question"],
            proposed_answer=prop.get("proposed_answer", ""),
            claims=claims,
            answer_verdict=prop.get("answer_verdict", "ABSTAIN"),
            confidence=float(prop.get("confidence", 0.5)),
            conflicting_sources=list(prop.get("conflicting_sources") or []),
            abstain_reason=prop.get("abstain_reason"),
            metadata=dict(prop.get("metadata") or {}),
        )
        decision = evaluate_proposal(gin, corpus)
        citations: list[str] = []
        for c in claims:
            citations.extend(c.source_ids)
        citations = sorted(set(citations))

        gdict = {
            "decision": decision.decision.value,
            "reason_code": decision.reason_code,
            "detail": decision.detail,
            "answer_verdict": decision.answer_verdict,
            "grounded_claim_count": decision.grounded_claim_count,
            "ungrounded_claim_count": decision.ungrounded_claim_count,
            "invalid_citations": decision.invalid_citations,
        }

        # Persist answer audit + question status
        if decision.decision == Decision.ALLOW:
            status = "answered"
            final = prop.get("proposed_answer")
        elif decision.decision == Decision.HOLD:
            status = "held"
            final = None
            corpus.append_exception(
                reason_code=decision.reason_code,
                detail=decision.detail,
                question_id=state["question_id"],
            )
        else:
            status = "blocked"
            final = None
            corpus.append_exception(
                reason_code=decision.reason_code,
                detail=decision.detail,
                question_id=state["question_id"],
            )

        corpus.append_answer(
            question_id=state["question_id"],
            proposed_answer=prop.get("proposed_answer", ""),
            guardrail_verdict=decision.decision.value,
            final_answer=final,
            actor="agent",
            reason=decision.reason_code,
            citations=citations,
        )
        corpus.upsert_question(
            {
                "id": state["question_id"],
                "text": state["question"],
                "status": status,
                "proposed_answer": prop.get("proposed_answer"),
                "guardrail_decision": decision.decision.value,
                "guardrail_reason": decision.reason_code,
                "citations": citations,
                "final_verdict": decision.answer_verdict,
                "final_answer": final,
            }
        )
        corpus.append_memory(
            kind="verdict",
            content=f"{decision.decision.value}:{decision.reason_code}",
            source="agent_loop",
            question_id=state["question_id"],
        )

        # Re-check pause after logging this answer (streaks / rates)
        pause2 = checker.check()
        paused = False
        pause_reason = None
        if pause2.should_pause:
            checker.apply_if_needed(pause2, state["question_id"])
            paused = True
            pause_reason = pause2.reason_code

        return {
            **state,
            "guardrail": gdict,
            "final_status": status,
            "final_answer": final,
            "citations": citations,
            "paused": paused,
            "pause_reason": pause_reason,
        }

    graph = StateGraph(AgentState)
    graph.add_node("fetch_question", fetch_question)
    graph.add_node("recall_memory", recall_memory)
    graph.add_node("retrieve", retrieve)
    graph.add_node("propose", propose)
    graph.add_node("guardrail", guardrail_node)
    graph.set_entry_point("fetch_question")
    graph.add_edge("fetch_question", "recall_memory")
    graph.add_edge("recall_memory", "retrieve")
    graph.add_edge("retrieve", "propose")
    graph.add_edge("propose", "guardrail")
    graph.add_edge("guardrail", END)
    return graph.compile()


def run_agent(
    corpus: GovernedCorpus,
    *,
    question_id: str,
    question: str,
    scenario: str | None = None,
) -> dict[str, Any]:
    if corpus.is_paused():
        return {
            "question_id": question_id,
            "final_status": "paused",
            "paused": True,
            "pause_reason": corpus.get_control("pause_reason"),
            "final_answer": None,
            "cost_usd": 0.0,
            "guardrail": {
                "decision": "BLOCK",
                "reason_code": "agent_paused",
                "detail": "Agent is paused until a human clears it.",
            },
            "citations": [],
        }
    app = build_graph(corpus)
    result = app.invoke(
        {
            "question_id": question_id,
            "question": question,
            "scenario": scenario or "",
            "cost_usd": 0.0,
        }
    )
    return dict(result)
