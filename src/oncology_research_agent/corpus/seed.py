"""Deterministic synthetic corpus seed (seed=42). All entities are labelled SYNTHETIC."""

from __future__ import annotations

import json
import random
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from oncology_research_agent.config import CORPUS_SEED, CORPUS_VERSION
from oncology_research_agent.corpus.schema import connect, init_schema

# Synthetic-only names — never real drugs, trials, or patients.
TARGETS = [
    "SYN-EGFR",
    "SYN-HER2",
    "SYN-KRAS-G12C",
    "SYN-BRAF-V600",
    "SYN-ALK",
    "SYN-MET",
    "SYN-RET",
    "SYN-ROS1",
    "SYN-FGFR2",
    "SYN-PI3K-alpha",
    "SYN-mTOR",
    "SYN-CDK4/6",
    "SYN-PARP",
    "SYN-BCL2",
    "SYN-MYC",
    "SYN-WNT",
    "SYN-NOTCH",
    "SYN-HIF1A",
    "SYN-AXL",
    "SYN-CSF1R",
]

INDICATIONS = [
    "synthetic NSCLC cohort A",
    "synthetic HER2+ breast neoplasia cohort B",
    "synthetic CRC microsatellite-stable cohort C",
    "synthetic melanoma BRAF-mutant cohort D",
    "synthetic ovarian high-grade serous cohort E",
    "synthetic pancreatic ductal cohort F",
    "synthetic glioblastoma cohort G",
    "synthetic RCC clear-cell cohort H",
    "synthetic AML molecular subtype I",
    "synthetic prostate CRPC cohort J",
    "synthetic gastric HER2-low cohort K",
    "synthetic cholangiocarcinoma FGFR cohort L",
]

JOURNALS = [
    "Synthetic Oncology Letters",
    "Journal of Experimental Tumor Biology (Synthetic)",
    "Virtual Cancer Therapeutics Quarterly",
    "Demo Molecular Oncology",
    "Simulated Clinical Cancer Research",
]

AUTHOR_FIRST = [
    "Amina",
    "Diego",
    "Priya",
    "Jonah",
    "Mei",
    "Lars",
    "Sofia",
    "Kenji",
    "Nora",
    "Omar",
    "Elena",
    "Theo",
]
AUTHOR_LAST = [
    "Vega",
    "Okoro",
    "Singh",
    "Berg",
    "Chen",
    "Duarte",
    "Hassan",
    "Ito",
    "Novak",
    "Patel",
    "Rossi",
    "Walsh",
]

PATHWAYS = [
    "synthetic MAPK cascade",
    "synthetic PI3K/AKT axis",
    "synthetic DNA-repair checkpoint",
    "synthetic hypoxia response",
    "synthetic immune-checkpoint modulation",
    "synthetic cell-cycle gatekeeping",
    "synthetic apoptosis priming",
    "synthetic angiogenesis switch",
    "synthetic epigenetic silencing",
    "synthetic metabolic rewiring",
]

PHASES = ["I", "II", "III"]
STATUSES = ["recruiting", "active", "completed"]
STAGES = ["preclinical", "phase-I", "phase-II", "phase-III"]


def _authors(rng: random.Random, n: int = 3) -> str:
    names = [f"{rng.choice(AUTHOR_FIRST)} {rng.choice(AUTHOR_LAST)}" for _ in range(n)]
    return ", ".join(names)


def _findings(rng: random.Random, target: str, indication: str) -> list[str]:
    templates = [
        f"In a synthetic cohort, {target} inhibition reduced marker SYN-MKI67 by "
        f"{rng.randint(18, 62)}% versus vehicle.",
        f"Combination with synthetic checkpoint modulator SYN-CPX raised ORR to "
        f"{rng.randint(22, 58)}% in {indication}.",
        f"Dose-limiting toxicity was SYN-grade-{rng.choice(['2', '3'])} "
        f"{rng.choice(['rash', 'fatigue', 'transaminase elevation'])} "
        f"at {rng.choice([100, 200, 400])} mg.",
        f"Biomarker SYN-{rng.choice(['PDL1', 'TMB', 'ctDNA'])} predicted response "
        f"with AUC {rng.uniform(0.62, 0.88):.2f} in held-out synthetic folds.",
    ]
    return rng.sample(templates, k=rng.randint(2, 3))


def generate_drugs(rng: random.Random, n: int = 40) -> list[dict]:
    drugs = []
    for i in range(1, n + 1):
        target = TARGETS[(i - 1) % len(TARGETS)]
        drugs.append(
            {
                "id": f"ONC-{100 + i}",
                "mechanism": f"synthetic {target} modulator",
                "molecular_target": target,
                "development_stage": STAGES[(i - 1) % len(STAGES)],
                "indication_focus": INDICATIONS[(i - 1) % len(INDICATIONS)],
                "synthetic_label": "SYNTHETIC",
            }
        )
    return drugs


def generate_mechanisms(rng: random.Random, drugs: list[dict], n: int = 25) -> list[dict]:
    mechs = []
    for i in range(1, n + 1):
        related = [d["id"] for d in rng.sample(drugs, k=min(3, len(drugs)))]
        pathway = PATHWAYS[(i - 1) % len(PATHWAYS)]
        mechs.append(
            {
                "id": f"MEC-{i:03d}",
                "pathway": pathway,
                "description": (
                    f"SYNTHETIC pathway description: {pathway} links "
                    f"{related[0]} activity to downstream SYN-TF signalling "
                    f"in modelled tumor microenvironments."
                ),
                "related_drug_ids": json.dumps(related),
                "synthetic_label": "SYNTHETIC",
            }
        )
    return mechs


def generate_papers(rng: random.Random, drugs: list[dict], n: int = 120) -> list[dict]:
    papers = []
    for i in range(1, n + 1):
        drug = drugs[(i - 1) % len(drugs)]
        target = drug["molecular_target"]
        indication = drug["indication_focus"]
        year = rng.randint(2018, 2025)
        title = f"SYNTHETIC study: {target} modulation with {drug['id']} in {indication}"
        findings = _findings(rng, target, indication)
        abstract = (
            f"[SYNTHETIC] We evaluated {drug['id']} ({drug['mechanism']}) in a "
            f"modelled {indication}. Primary readouts included SYN-MKI67 and "
            f"synthetic ORR. Key observations: {findings[0]}"
        )
        papers.append(
            {
                "id": f"PAP-{i:03d}",
                "title": title,
                "authors": _authors(rng),
                "journal": rng.choice(JOURNALS),
                "year": year,
                "abstract": abstract,
                "key_findings": json.dumps(findings),
                "synthetic_label": "SYNTHETIC",
            }
        )
    return papers


def generate_trials(rng: random.Random, drugs: list[dict], n: int = 60) -> list[dict]:
    trials = []
    for i in range(1, n + 1):
        drug = drugs[(i - 1) % len(drugs)]
        related = [drug["id"]]
        if i % 3 == 0:
            other = drugs[i % len(drugs)]
            if other["id"] != drug["id"]:
                related.append(other["id"])
        phase = PHASES[(i - 1) % len(PHASES)]
        enrollment = {
            "I": rng.randint(12, 40),
            "II": rng.randint(40, 120),
            "III": rng.randint(120, 600),
        }[phase]
        trials.append(
            {
                "id": f"TRL-{i:03d}",
                "phase": phase,
                "indication": drug["indication_focus"],
                "enrollment": enrollment,
                "primary_endpoint": rng.choice(
                    [
                        "synthetic ORR at 12 weeks",
                        "synthetic PFS by central review",
                        "synthetic DLT rate in cycle 1",
                        "synthetic OS landmark at 18 months",
                        "synthetic biomarker response SYN-ctDNA clearance",
                    ]
                ),
                "status": STATUSES[(i - 1) % len(STATUSES)],
                "related_drug_ids": json.dumps(related),
                "synthetic_label": "SYNTHETIC",
            }
        )
    return trials


def _insert_many(conn: sqlite3.Connection, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    cols = list(rows[0].keys())
    placeholders = ", ".join("?" for _ in cols)
    col_sql = ", ".join(cols)
    conn.executemany(
        f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders})",
        [tuple(r[c] for c in cols) for r in rows],
    )


def seed_corpus(
    db_path: Path,
    *,
    seed: int = CORPUS_SEED,
    force: bool = False,
) -> dict[str, int]:
    """Create schema and populate synthetic corpus. Returns row counts."""
    conn = connect(db_path)
    try:
        init_schema(conn)
        existing = conn.execute("SELECT value FROM meta WHERE key = 'corpus_version'").fetchone()
        if existing and not force:
            counts = _counts(conn)
            counts["corpus_version"] = existing["value"]
            return counts

        for table in (
            "papers",
            "trials",
            "drugs",
            "mechanisms",
            "answers",
            "memory",
            "exceptions",
            "questions",
            "controls_state",
            "meta",
        ):
            conn.execute(f"DELETE FROM {table}")

        rng = random.Random(seed)
        drugs = generate_drugs(rng)
        mechs = generate_mechanisms(rng, drugs)
        papers = generate_papers(rng, drugs)
        trials = generate_trials(rng, drugs)

        _insert_many(conn, "drugs", drugs)
        _insert_many(conn, "mechanisms", mechs)
        _insert_many(conn, "papers", papers)
        _insert_many(conn, "trials", trials)

        now = datetime.now(UTC).isoformat()
        meta = {
            "corpus_version": CORPUS_VERSION,
            "seed": str(seed),
            "updated_at": now,
            "synthetic": "true",
            "paused": "false",
        }
        for k, v in meta.items():
            conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?)",
                (k, v),
            )
        conn.execute(
            "INSERT INTO controls_state (key, value) VALUES (?, ?)",
            ("paused", "false"),
        )
        conn.execute(
            "INSERT INTO controls_state (key, value) VALUES (?, ?)",
            ("pause_reason", ""),
        )
        conn.commit()
        counts = _counts(conn)
        counts["corpus_version"] = CORPUS_VERSION
        return counts
    finally:
        conn.close()


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    out: dict[str, int] = {}
    for table in ("papers", "trials", "drugs", "mechanisms"):
        row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
        out[table] = int(row["c"])
    return out


def refresh_updated_at(db_path: Path) -> None:
    """Bump corpus updated_at to now (for freshness checks)."""
    conn = connect(db_path)
    try:
        now = datetime.now(UTC).isoformat()
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('updated_at', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (now,),
        )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    from oncology_research_agent.config import db_path

    path = db_path()
    counts = seed_corpus(path, force=True)
    print(json.dumps(counts, indent=2))
