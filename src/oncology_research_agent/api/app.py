"""FastAPI demo API + static dashboard."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from oncology_research_agent.config import PROJECT_ROOT, db_path
from oncology_research_agent.controls.digest import compute_digest
from oncology_research_agent.corpus.governed import GovernedCorpus
from oncology_research_agent.corpus.seed import refresh_updated_at, seed_corpus
from oncology_research_agent.review.queue import approve, reject

STATIC_DIR = PROJECT_ROOT / "static"
REPORTS_DIR = PROJECT_ROOT / "evals" / "reports"


def get_corpus() -> GovernedCorpus:
    path = db_path()
    if not path.exists():
        seed_corpus(path, force=True)
        refresh_updated_at(path)
    return GovernedCorpus(path)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    path = db_path()
    seed_corpus(path, force=False)
    refresh_updated_at(path)
    yield


app = FastAPI(
    title="oncology-research-agent",
    description="Bounded scientific agent demo over a synthetic oncology corpus.",
    version="0.1.0",
    lifespan=lifespan,
)


class ReviewBody(BaseModel):
    action: str = Field(..., pattern="^(approve|reject)$")
    reason: str
    actor: str = "reviewing_scientist"


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/questions")
def list_questions(status: str | None = None) -> list[dict[str, Any]]:
    return get_corpus().list_questions(status=status)


@app.get("/questions/{question_id}")
def get_question(question_id: str) -> dict[str, Any]:
    q = get_corpus().get_question(question_id)
    if q is None:
        raise HTTPException(404, "question not found")
    return q


@app.post("/questions/{question_id}/review")
def review_question(question_id: str, body: ReviewBody) -> dict[str, Any]:
    corpus = get_corpus()
    try:
        if body.action == "approve":
            return approve(corpus, question_id, reason=body.reason, actor=body.actor)
        return reject(corpus, question_id, reason=body.reason, actor=body.actor)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/controls/digest")
def controls_digest() -> dict[str, Any]:
    return compute_digest(get_corpus())


@app.get("/evals/latest")
def evals_latest(mode: str = "stub") -> dict[str, Any]:
    path = REPORTS_DIR / f"latest-{mode}.json"
    if not path.exists():
        candidates = sorted(REPORTS_DIR.glob(f"*-{mode}.json"))
        if not candidates:
            raise HTTPException(404, "no eval report committed")
        path = candidates[-1]
    return json.loads(path.read_text())


@app.get("/")
def dashboard() -> FileResponse:
    index = STATIC_DIR / "index.html"
    if not index.exists():
        raise HTTPException(404, "dashboard not built yet")
    return FileResponse(index)


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
