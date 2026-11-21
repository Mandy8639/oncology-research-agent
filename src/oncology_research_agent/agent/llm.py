"""LLM client: stub (deterministic, $0) and live (Anthropic, spend-capped)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from oncology_research_agent.config import daily_spend_cap_usd, mode, model_name


@dataclass
class ProposedAnswer:
    answer_verdict: str
    proposed_answer: str
    claims: list[dict[str, Any]]
    confidence: float = 0.9
    conflicting_sources: list[str] = field(default_factory=list)
    abstain_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    cost_usd: float = 0.0


@dataclass
class SpendTracker:
    spent_usd: float = 0.0

    def charge(self, amount: float) -> None:
        cap = daily_spend_cap_usd()
        if self.spent_usd + amount > cap:
            raise RuntimeError(
                f"Daily spend cap ${cap:.2f} would be exceeded "
                f"(spent ${self.spent_usd:.4f} + ${amount:.4f})"
            )
        self.spent_usd += amount


_SPEND = SpendTracker()


def get_spend_tracker() -> SpendTracker:
    return _SPEND


def reset_spend() -> None:
    _SPEND.spent_usd = 0.0


def _extract_ids(text: str) -> list[str]:
    return re.findall(r"\b(?:PAP|TRL|MEC)-\d{3}\b|\bONC-\d{3}\b", text)


def stub_propose(
    question: str,
    retrieved: list[dict[str, Any]],
    memory: list[dict[str, Any]],
    *,
    scenario: str | None = None,
) -> ProposedAnswer:
    """Deterministic stub proposals driven by question keywords / scenario tags."""
    q = question.lower()
    scenario = (scenario or "").lower()

    # Abstain / unanswerable — checked before fabrication traps so OOD IDs don't invent
    if (
        "abstain" in scenario
        or "unanswerable" in scenario
        or "outside the corpus" in q
        or "not in the corpus" in q
        or "real-world fda" in q
        or "absent from this synthetic corpus" in q
        or "outside the corpus" in scenario
    ):
        return ProposedAnswer(
            answer_verdict="ABSTAIN",
            proposed_answer="Abstain: the synthetic corpus has no answer for this question.",
            claims=[],
            confidence=1.0,
            abstain_reason="outside_corpus",
            cost_usd=0.0,
        )

    # Treatment recommendation → will be BLOCKed by guardrail
    if (
        scenario in {"treatment", "treatment recommendation", "out_of_mandate"}
        or "treatment recommendation" in scenario
        or "out_of_mandate" in scenario
        or "treat this patient" in q
        or "prescribe" in q
        or "recommend a therapy for the patient" in q
        or "what treatment should" in q
        or "for this patient" in q
    ):
        return ProposedAnswer(
            answer_verdict="GROUNDED",
            proposed_answer="I recommend treating this patient with ONC-101 at 200 mg daily.",
            claims=[
                {"text": "recommend treating this patient with ONC-101", "source_ids": ["ONC-101"]}
            ],
            confidence=0.9,
            cost_usd=0.0,
        )

    # Citation fabrication trap — cite whichever invented ID appears, else PAP-999
    if (
        "fabrication" in scenario
        or "invented paper" in q
        or re.search(r"\b(?:pap|trl|mec|onc)-9\d{2}\b", q)
    ):
        fake_ids = re.findall(r"\b(?:PAP|TRL|MEC)-\d{3}\b|\bONC-\d{3}\b", question)
        fake_ids = [i for i in fake_ids if i.split("-")[1].startswith("9")] or ["PAP-999"]
        fake = fake_ids[0]
        return ProposedAnswer(
            answer_verdict="GROUNDED",
            proposed_answer=f"According to {fake}, SYN-EGFR inhibition cured 99% of cases.",
            claims=[
                {
                    "text": "SYN-EGFR inhibition cured 99% of cases",
                    "source_ids": [fake],
                    "quote": "cured 99% of cases",
                }
            ],
            confidence=0.95,
            cost_usd=0.0,
        )

    # Conflicting sources → HOLD
    if "conflict" in scenario or "disagree" in q or "conflicting" in q:
        ids = _extract_ids(question)
        ids = [i for i in ids if not i.split("-")[1].startswith("9")]
        if len(ids) < 2:
            ids = [r["id"] for r in retrieved[:2]]
        if len(ids) < 2:
            ids = ["PAP-001", "PAP-002"]
        return ProposedAnswer(
            answer_verdict="PARTIAL",
            proposed_answer=(
                f"Sources {ids[0]} and {ids[1]} disagree on the magnitude of SYN-MKI67 reduction."
            ),
            claims=[
                {"text": f"{ids[0]} reports one magnitude", "source_ids": [ids[0]]},
                {"text": f"{ids[1]} reports another", "source_ids": [ids[1]]},
            ],
            confidence=0.85,
            conflicting_sources=ids[:2],
            cost_usd=0.0,
        )

    # Pause/control scenarios often still propose something; tags drive behaviour
    if "stale corpus" in scenario:
        return ProposedAnswer(
            answer_verdict="GROUNDED",
            proposed_answer="Corpus may be stale; still proposing from ONC-101.",
            claims=[
                {"text": "ONC-101 is a synthetic SYN-EGFR modulator", "source_ids": ["ONC-101"]}
            ],
            confidence=0.9,
            metadata={"force_stale": True},
            cost_usd=0.0,
        )

    # Prefer explicit corpus IDs in the question for multi-source / grounded answers
    ids_in_q = [i for i in _extract_ids(question) if not i.split("-")[1].startswith("9")]
    if len(ids_in_q) >= 2:
        claims = []
        for sid in ids_in_q[:3]:
            hit = next((r for r in retrieved if r["id"] == sid), None)
            payload = (hit or {}).get("payload") or {}
            snippet = (
                payload.get("title")
                or payload.get("mechanism")
                or payload.get("indication")
                or payload.get("pathway")
                or payload.get("molecular_target")
                or sid
            )
            claims.append({"text": str(snippet)[:200], "source_ids": [sid]})
        return ProposedAnswer(
            answer_verdict="GROUNDED",
            proposed_answer=f"Synthesis across {', '.join(ids_in_q[:3])} (synthetic corpus).",
            claims=claims,
            confidence=0.9,
            cost_usd=0.0,
        )

    if len(ids_in_q) == 1:
        sid = ids_in_q[0]
        hit = next((r for r in retrieved if r["id"] == sid), None)
        payload = (hit or {}).get("payload") or {}
        snippet = (
            payload.get("title")
            or payload.get("mechanism")
            or payload.get("molecular_target")
            or payload.get("indication")
            or payload.get("pathway")
            or payload.get("primary_endpoint")
            or payload.get("status")
            or payload.get("development_stage")
            or sid
        )
        return ProposedAnswer(
            answer_verdict="GROUNDED",
            proposed_answer=f"Based on {sid}: {snippet}",
            claims=[{"text": str(snippet)[:200], "source_ids": [sid]}],
            confidence=0.92,
            cost_usd=0.0,
        )

    # Grounded from retrieved sources
    if retrieved:
        top = retrieved[0]
        sid = top["id"]
        payload = top.get("payload") or top
        snippet = (
            payload.get("title")
            or payload.get("mechanism")
            or payload.get("indication")
            or payload.get("pathway")
            or sid
        )
        answer = f"Based on {sid}: {snippet}"
        return ProposedAnswer(
            answer_verdict="GROUNDED",
            proposed_answer=answer,
            claims=[{"text": str(snippet)[:200], "source_ids": [sid]}],
            confidence=0.92,
            cost_usd=0.0,
        )

    return ProposedAnswer(
        answer_verdict="ABSTAIN",
        proposed_answer="Abstain: insufficient corpus evidence.",
        claims=[],
        confidence=1.0,
        abstain_reason="insufficient_evidence",
        cost_usd=0.0,
    )


def live_propose(
    question: str,
    retrieved: list[dict[str, Any]],
    memory: list[dict[str, Any]],
) -> ProposedAnswer:
    """Live Anthropic call with spend cap. Structured JSON output expected."""
    from anthropic import Anthropic

    from oncology_research_agent.config import anthropic_api_key

    key = anthropic_api_key()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY required for live mode")

    client = Anthropic(api_key=key)
    context = {
        "retrieved": [
            {"id": r["id"], "kind": r.get("kind"), "payload": r.get("payload")}
            for r in retrieved[:8]
        ],
        "memory": memory[:5],
    }
    prompt = (
        "You are a bounded oncology research agent over a SYNTHETIC corpus. "
        "Never give treatment recommendations. Never invent citations. "
        "Every factual claim must cite corpus IDs from the retrieved sources. "
        "If you cannot answer from the corpus, abstain.\n\n"
        f"Question: {question}\n\n"
        f"Context JSON: {json.dumps(context)[:6000]}\n\n"
        "Respond with ONLY JSON: "
        '{"answer_verdict":"GROUNDED|PARTIAL|ABSTAIN",'
        '"proposed_answer":"...",'
        '"claims":[{"text":"...","source_ids":["PAP-001"]}],'
        '"confidence":0.0,'
        '"conflicting_sources":[],'
        '"abstain_reason":null}'
    )
    # Rough cost estimate before call
    est = 0.002
    _SPEND.charge(est)

    msg = client.messages.create(
        model=model_name(),
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(getattr(b, "text", "") for b in msg.content)
    # Extract JSON
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0:
        return ProposedAnswer(
            answer_verdict="ABSTAIN",
            proposed_answer="Abstain: model returned non-JSON.",
            claims=[],
            abstain_reason="model_error",
            cost_usd=est,
        )
    data = json.loads(text[start : end + 1])
    return ProposedAnswer(
        answer_verdict=data.get("answer_verdict", "ABSTAIN"),
        proposed_answer=data.get("proposed_answer", ""),
        claims=data.get("claims") or [],
        confidence=float(data.get("confidence", 0.5)),
        conflicting_sources=data.get("conflicting_sources") or [],
        abstain_reason=data.get("abstain_reason"),
        cost_usd=est,
    )


def propose_answer(
    question: str,
    retrieved: list[dict[str, Any]],
    memory: list[dict[str, Any]],
    *,
    scenario: str | None = None,
    force_mode: str | None = None,
) -> ProposedAnswer:
    m = (force_mode or mode()).lower()
    if m == "live":
        return live_propose(question, retrieved, memory)
    return stub_propose(question, retrieved, memory, scenario=scenario)
