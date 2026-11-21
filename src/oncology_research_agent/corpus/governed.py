"""Governed corpus access: views only, freshness check, contamination safeguard."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from oncology_research_agent.config import (
    FRESHNESS_MAX_AGE_HOURS,
    corpus_version,
    db_path,
)
from oncology_research_agent.corpus.schema import connect


@dataclass(frozen=True)
class FreshnessResult:
    ok: bool
    reason: str
    updated_at: str | None
    expected_version: str
    actual_version: str | None


@dataclass(frozen=True)
class SourceRecord:
    id: str
    kind: str
    payload: dict[str, Any]


class GovernedCorpus:
    """All agent reads go through this module — no raw table access for callers."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or db_path()

    def _conn(self) -> sqlite3.Connection:
        return connect(self.path)

    def get_meta(self, key: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
            return None if row is None else str(row["value"])

    def freshness_check(self) -> FreshnessResult:
        expected = corpus_version()
        actual = self.get_meta("corpus_version")
        updated_raw = self.get_meta("updated_at")
        if actual is None:
            return FreshnessResult(
                ok=False,
                reason="missing_corpus_version",
                updated_at=updated_raw,
                expected_version=expected,
                actual_version=None,
            )
        if actual != expected:
            return FreshnessResult(
                ok=False,
                reason="corpus_version_mismatch",
                updated_at=updated_raw,
                expected_version=expected,
                actual_version=actual,
            )
        if not updated_raw:
            return FreshnessResult(
                ok=False,
                reason="missing_updated_at",
                updated_at=None,
                expected_version=expected,
                actual_version=actual,
            )
        updated = datetime.fromisoformat(updated_raw)
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=UTC)
        age_hours = (datetime.now(UTC) - updated).total_seconds() / 3600
        if age_hours > FRESHNESS_MAX_AGE_HOURS:
            return FreshnessResult(
                ok=False,
                reason="corpus_stale",
                updated_at=updated_raw,
                expected_version=expected,
                actual_version=actual,
            )
        return FreshnessResult(
            ok=True,
            reason="ok",
            updated_at=updated_raw,
            expected_version=expected,
            actual_version=actual,
        )

    def counts(self) -> dict[str, int]:
        with self._conn() as conn:
            out: dict[str, int] = {}
            for table in ("papers", "trials", "drugs", "mechanisms"):
                row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
                out[table] = int(row["c"])
            return out

    def source_exists(self, source_id: str) -> bool:
        return self.get_source(source_id) is not None

    def get_source(self, source_id: str) -> SourceRecord | None:
        table_map = {
            "PAP-": ("papers", "paper"),
            "TRL-": ("trials", "trial"),
            "ONC-": ("drugs", "drug"),
            "MEC-": ("mechanisms", "mechanism"),
        }
        for pfx, (table, kind) in table_map.items():
            if source_id.startswith(pfx):
                with self._conn() as conn:
                    row = conn.execute(
                        f"SELECT * FROM {table} WHERE id = ?", (source_id,)
                    ).fetchone()
                    if row is None:
                        return None
                    return SourceRecord(id=source_id, kind=kind, payload=dict(row))
        return None

    def search(
        self,
        query: str,
        *,
        kinds: list[str] | None = None,
        limit: int = 10,
    ) -> list[SourceRecord]:
        """Keyword search over governed views (title/abstract/indication/etc.)."""
        q = query.strip().lower()
        if not q:
            return []
        allowed = kinds or ["paper", "trial", "drug", "mechanism"]
        results: list[SourceRecord] = []
        with self._conn() as conn:
            if "paper" in allowed:
                rows = conn.execute(
                    "SELECT * FROM papers WHERE lower(title) LIKE ? "
                    "OR lower(abstract) LIKE ? OR lower(key_findings) LIKE ? "
                    "LIMIT ?",
                    (f"%{q}%", f"%{q}%", f"%{q}%", limit),
                ).fetchall()
                results.extend(
                    SourceRecord(id=r["id"], kind="paper", payload=dict(r)) for r in rows
                )
            if "trial" in allowed:
                rows = conn.execute(
                    "SELECT * FROM trials WHERE lower(indication) LIKE ? "
                    "OR lower(primary_endpoint) LIKE ? OR id LIKE ? LIMIT ?",
                    (f"%{q}%", f"%{q}%", f"%{q}%", limit),
                ).fetchall()
                results.extend(
                    SourceRecord(id=r["id"], kind="trial", payload=dict(r)) for r in rows
                )
            if "drug" in allowed:
                rows = conn.execute(
                    "SELECT * FROM drugs WHERE lower(mechanism) LIKE ? "
                    "OR lower(molecular_target) LIKE ? OR id LIKE ? LIMIT ?",
                    (f"%{q}%", f"%{q}%", f"%{q}%", limit),
                ).fetchall()
                results.extend(SourceRecord(id=r["id"], kind="drug", payload=dict(r)) for r in rows)
            if "mechanism" in allowed:
                rows = conn.execute(
                    "SELECT * FROM mechanisms WHERE lower(pathway) LIKE ? "
                    "OR lower(description) LIKE ? OR id LIKE ? LIMIT ?",
                    (f"%{q}%", f"%{q}%", f"%{q}%", limit),
                ).fetchall()
                results.extend(
                    SourceRecord(id=r["id"], kind="mechanism", payload=dict(r)) for r in rows
                )
        return results[:limit]

    def quote_supported(self, source_id: str, quote: str) -> bool:
        """True if quote is a substring of the source's textual fields."""
        src = self.get_source(source_id)
        if src is None:
            return False
        blob = " ".join(str(v) for v in src.payload.values()).lower()
        return quote.strip().lower() in blob

    def all_source_ids(self) -> set[str]:
        ids: set[str] = set()
        with self._conn() as conn:
            for table in ("papers", "trials", "drugs", "mechanisms"):
                rows = conn.execute(f"SELECT id FROM {table}").fetchall()
                ids.update(r["id"] for r in rows)
        return ids

    def corpus_text_blob(self) -> str:
        """Concatenated corpus text for contamination checks."""
        parts: list[str] = []
        with self._conn() as conn:
            for table, cols in (
                ("papers", ("title", "abstract", "key_findings", "authors")),
                ("trials", ("indication", "primary_endpoint")),
                ("drugs", ("mechanism", "molecular_target", "indication_focus")),
                ("mechanisms", ("pathway", "description")),
            ):
                rows = conn.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
                for row in rows:
                    parts.extend(str(row[c]) for c in cols)
        return "\n".join(parts).lower()

    def assert_no_contamination(self, forbidden_texts: list[str]) -> list[str]:
        """Return any forbidden strings found in corpus text (should be empty)."""
        blob = self.corpus_text_blob()
        hits: list[str] = []
        for text in forbidden_texts:
            t = text.strip().lower()
            if len(t) < 12:
                continue
            if t in blob:
                hits.append(text)
        return hits

    def memory_contains_forbidden(self, forbidden_texts: list[str]) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute("SELECT content FROM memory").fetchall()
        blob = "\n".join(r["content"] for r in rows).lower()
        hits: list[str] = []
        for text in forbidden_texts:
            t = text.strip().lower()
            if len(t) < 12:
                continue
            if t in blob:
                hits.append(text)
        return hits

    def list_recent_answers(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM answers ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def append_answer(
        self,
        *,
        question_id: str,
        proposed_answer: str,
        guardrail_verdict: str,
        final_answer: str | None,
        actor: str,
        reason: str,
        citations: list[str],
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO answers "
                "(question_id, proposed_answer, guardrail_verdict, final_answer, "
                "actor, reason, citations, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    question_id,
                    proposed_answer,
                    guardrail_verdict,
                    final_answer,
                    actor,
                    reason,
                    json.dumps(citations),
                    now,
                ),
            )
            conn.commit()

    def append_memory(
        self,
        *,
        kind: str,
        content: str,
        source: str,
        question_id: str | None = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO memory (kind, content, source, question_id, timestamp) "
                "VALUES (?, ?, ?, ?, ?)",
                (kind, content, source, question_id, now),
            )
            conn.commit()

    def recall_memory(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM memory ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def append_exception(
        self,
        *,
        reason_code: str,
        detail: str,
        question_id: str | None = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO exceptions (question_id, reason_code, detail, timestamp) "
                "VALUES (?, ?, ?, ?)",
                (question_id, reason_code, detail, now),
            )
            conn.commit()

    def list_exceptions(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM exceptions ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_control(self, key: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM controls_state WHERE key = ?", (key,)).fetchone()
            return None if row is None else str(row["value"])

    def set_control(self, key: str, value: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO controls_state (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            conn.commit()

    def is_paused(self) -> bool:
        return self.get_control("paused") == "true"

    def set_paused(self, paused: bool, reason: str = "") -> None:
        self.set_control("paused", "true" if paused else "false")
        self.set_control("pause_reason", reason)

    def upsert_question(self, question: dict[str, Any]) -> None:
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT id FROM questions WHERE id = ?", (question["id"],)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE questions SET text = ?, status = ?, proposed_answer = ?, "
                    "guardrail_decision = ?, guardrail_reason = ?, citations = ?, "
                    "final_verdict = ?, final_answer = ?, updated_at = ? WHERE id = ?",
                    (
                        question.get("text", ""),
                        question.get("status", "pending"),
                        question.get("proposed_answer"),
                        question.get("guardrail_decision"),
                        question.get("guardrail_reason"),
                        json.dumps(question.get("citations") or []),
                        question.get("final_verdict"),
                        question.get("final_answer"),
                        now,
                        question["id"],
                    ),
                )
            else:
                conn.execute(
                    "INSERT INTO questions "
                    "(id, text, status, proposed_answer, guardrail_decision, "
                    "guardrail_reason, citations, final_verdict, final_answer, "
                    "created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        question["id"],
                        question.get("text", ""),
                        question.get("status", "pending"),
                        question.get("proposed_answer"),
                        question.get("guardrail_decision"),
                        question.get("guardrail_reason"),
                        json.dumps(question.get("citations") or []),
                        question.get("final_verdict"),
                        question.get("final_answer"),
                        now,
                        now,
                    ),
                )
            conn.commit()

    def get_question(self, question_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()
            if row is None:
                return None
            d = dict(row)
            d["citations"] = json.loads(d.get("citations") or "[]")
            return d

    def list_questions(self, status: str | None = None) -> list[dict[str, Any]]:
        with self._conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM questions WHERE status = ? ORDER BY created_at DESC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM questions ORDER BY created_at DESC").fetchall()
            out = []
            for row in rows:
                d = dict(row)
                d["citations"] = json.loads(d.get("citations") or "[]")
                out.append(d)
            return out
