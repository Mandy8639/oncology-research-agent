"""SQLite schema for the synthetic oncology corpus and agent audit tables."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS papers (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    authors TEXT NOT NULL,
    journal TEXT NOT NULL,
    year INTEGER NOT NULL,
    abstract TEXT NOT NULL,
    key_findings TEXT NOT NULL,
    synthetic_label TEXT NOT NULL DEFAULT 'SYNTHETIC'
);

CREATE TABLE IF NOT EXISTS trials (
    id TEXT PRIMARY KEY,
    phase TEXT NOT NULL,
    indication TEXT NOT NULL,
    enrollment INTEGER NOT NULL,
    primary_endpoint TEXT NOT NULL,
    status TEXT NOT NULL,
    related_drug_ids TEXT NOT NULL DEFAULT '[]',
    synthetic_label TEXT NOT NULL DEFAULT 'SYNTHETIC'
);

CREATE TABLE IF NOT EXISTS drugs (
    id TEXT PRIMARY KEY,
    mechanism TEXT NOT NULL,
    molecular_target TEXT NOT NULL,
    development_stage TEXT NOT NULL,
    indication_focus TEXT NOT NULL,
    synthetic_label TEXT NOT NULL DEFAULT 'SYNTHETIC'
);

CREATE TABLE IF NOT EXISTS mechanisms (
    id TEXT PRIMARY KEY,
    pathway TEXT NOT NULL,
    description TEXT NOT NULL,
    related_drug_ids TEXT NOT NULL DEFAULT '[]',
    synthetic_label TEXT NOT NULL DEFAULT 'SYNTHETIC'
);

CREATE TABLE IF NOT EXISTS answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id TEXT NOT NULL,
    proposed_answer TEXT NOT NULL,
    guardrail_verdict TEXT NOT NULL,
    final_answer TEXT,
    actor TEXT NOT NULL,
    reason TEXT NOT NULL,
    citations TEXT NOT NULL DEFAULT '[]',
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL,
    question_id TEXT,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exceptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id TEXT,
    reason_code TEXT NOT NULL,
    detail TEXT NOT NULL,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS controls_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    proposed_answer TEXT,
    guardrail_decision TEXT,
    guardrail_reason TEXT,
    citations TEXT DEFAULT '[]',
    final_verdict TEXT,
    final_answer TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()
