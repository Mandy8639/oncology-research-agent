"""CLI: onco review / controls / seed / evals."""

from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

from oncology_research_agent.config import db_path
from oncology_research_agent.controls.digest import (
    alert_and_pause_if_needed,
    clear_pause,
)
from oncology_research_agent.corpus.governed import GovernedCorpus
from oncology_research_agent.corpus.seed import refresh_updated_at, seed_corpus
from oncology_research_agent.review.queue import approve, list_held, reject

app = typer.Typer(help="oncology-research-agent CLI", no_args_is_help=True)
review_app = typer.Typer(help="Review queue commands")
controls_app = typer.Typer(help="Detective controls")
app.add_typer(review_app, name="review")
app.add_typer(controls_app, name="controls")
console = Console()


def _corpus() -> GovernedCorpus:
    return GovernedCorpus(db_path())


@app.command("seed")
def seed_cmd(force: bool = typer.Option(False, help="Rebuild corpus")) -> None:
    counts = seed_corpus(db_path(), force=force)
    refresh_updated_at(db_path())
    console.print(counts)


@review_app.command("list")
def review_list() -> None:
    held = list_held(_corpus())
    table = Table(title="Held answers")
    table.add_column("id")
    table.add_column("reason")
    table.add_column("citations")
    table.add_column("proposal")
    for q in held:
        table.add_row(
            q["id"],
            str(q.get("guardrail_reason") or ""),
            ",".join(q.get("citations") or []),
            (q.get("proposed_answer") or "")[:80],
        )
    console.print(table)


@review_app.command("approve")
def review_approve(
    question_id: str,
    reason: str = typer.Option(..., "--reason"),
    actor: str = typer.Option("reviewing_scientist", "--actor"),
) -> None:
    q = approve(_corpus(), question_id, reason=reason, actor=actor)
    console.print(q)


@review_app.command("reject")
def review_reject(
    question_id: str,
    reason: str = typer.Option(..., "--reason"),
    actor: str = typer.Option("reviewing_scientist", "--actor"),
) -> None:
    q = reject(_corpus(), question_id, reason=reason, actor=actor)
    console.print(q)


@controls_app.command("digest")
def controls_digest() -> None:
    digest = alert_and_pause_if_needed(_corpus())
    console.print_json(json.dumps(digest))
    if digest.get("alert"):
        console.print(f"[bold red]ALERT[/bold red] {digest['alert']}")


@controls_app.command("clear-pause")
def controls_clear_pause(
    reason: str = typer.Option(..., "--reason"),
    actor: str = typer.Option("reviewing_scientist", "--actor"),
) -> None:
    digest = clear_pause(_corpus(), reason=reason, actor=actor)
    console.print_json(json.dumps(digest))


@app.command("ask")
def ask_cmd(
    question: str,
    question_id: str = typer.Option("CLI-Q", "--id"),
    scenario: str | None = typer.Option(None, "--scenario"),
) -> None:
    from oncology_research_agent.agent.loop import run_agent

    out = run_agent(
        _corpus(),
        question_id=question_id,
        question=question,
        scenario=scenario,
    )
    console.print_json(
        json.dumps(
            {
                k: out.get(k)
                for k in (
                    "question_id",
                    "final_status",
                    "final_answer",
                    "guardrail",
                    "citations",
                    "paused",
                    "pause_reason",
                    "cost_usd",
                )
            }
        )
    )


if __name__ == "__main__":
    app()
