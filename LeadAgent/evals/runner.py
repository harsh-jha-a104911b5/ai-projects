"""Eval runner: runs every scenario through the live agent loop, grades with assertions
+ LLM judge, and prints a report.

Usage:
    python evals/runner.py [--skip-judge] [--category CATEGORY] [--id ID] [--out FILE.json]

CI: Use --skip-judge for deterministic-only runs (no LLM calls).
Full eval: run without flags (requires billing-enabled GEMINI_API_KEY).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

import yaml
from rich.console import Console
from rich.table import Table

from agent.loop import AgentLoop
from evals.assertions import AssertionResult, all_passed, cosine_scores_from_session, run_assertions
from evals.judge import judge_conversation
from integrations.calendar_adapter import MockCalendarAdapter
from integrations.crm_adapter import MockCRMAdapter

console = Console()
DATASETS_DIR = Path(__file__).parent / "datasets"


# ── Data types ────────────────────────────────────────────────────────────────


@dataclass
class ScenarioResult:
    scenario_id: str
    category: str
    description: str
    assertions: list[AssertionResult]
    assertions_passed: bool
    judge_scores: dict[str, Any] | None
    tool_calls_made: list[str]
    escalated: bool
    booked: bool
    cosine_scores: list[float]
    responses: list[str]
    error: str | None = None


# ── Scenario loading ──────────────────────────────────────────────────────────


def load_scenarios(
    datasets_dir: Path,
    category_filter: str | None = None,
    id_filter: str | None = None,
) -> list[dict]:
    scenarios = []
    for yaml_file in sorted(datasets_dir.glob("*.yaml")):
        with open(yaml_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        for sc in data.get("scenarios", []):
            if category_filter and sc.get("category") != category_filter:
                continue
            if id_filter and sc.get("id") != id_filter:
                continue
            scenarios.append(sc)
    return scenarios


# ── Single scenario runner ────────────────────────────────────────────────────


async def run_scenario(scenario: dict, *, skip_judge: bool = False) -> ScenarioResult:
    cal = MockCalendarAdapter()
    crm = MockCRMAdapter()
    loop = AgentLoop(cal, crm=crm)

    history: list = []
    responses: list[str] = []
    user_turns: list[str] = scenario["turns"]
    error: str | None = None

    try:
        for user_msg in user_turns:
            resp, history = await loop.turn(user_msg, history)
            responses.append(resp)
    except Exception as exc:
        error = str(exc)
        console.print(f"  [red]Error in {scenario['id']}: {exc}[/red]")

    session = loop._session
    assertion_results = run_assertions(
        scenario.get("assertions", {}),
        session,
        responses,
    )

    judge_scores: dict | None = None
    if not skip_judge and not error and responses:
        try:
            zipped = list(zip(user_turns[:len(responses)], responses))
            judge_scores = await judge_conversation(
                description=scenario["description"],
                turns=zipped,
                rubric=scenario.get("rubric", "Evaluate the agent's overall performance."),
            )
        except Exception as exc:
            console.print(f"  [yellow]Judge failed for {scenario['id']}: {exc}[/yellow]")

    return ScenarioResult(
        scenario_id=scenario["id"],
        category=scenario["category"],
        description=scenario["description"],
        assertions=assertion_results,
        assertions_passed=all_passed(assertion_results),
        judge_scores=judge_scores,
        tool_calls_made=[tc["name"] for tc in session.tool_calls],
        escalated=len(session.escalations) > 0,
        booked=any(
            tc["name"] == "book_meeting" and "booking_id" in tc.get("result", {})
            for tc in session.tool_calls
        ),
        cosine_scores=cosine_scores_from_session(session),
        responses=responses,
        error=error,
    )


# ── Report ────────────────────────────────────────────────────────────────────


def print_report(results: list[ScenarioResult]) -> None:
    console.rule(f"[bold]LeadAgent Eval — {date.today()}[/bold]")
    console.print()

    # Main results table
    table = Table(show_lines=True)
    table.add_column("ID", style="dim", width=10)
    table.add_column("Category", width=26)
    table.add_column("Assertions", width=12)
    table.add_column("G", width=3, justify="center")
    table.add_column("T", width=3, justify="center")
    table.add_column("Q", width=3, justify="center")
    table.add_column("E", width=3, justify="center")
    table.add_column("Tools called", width=32)
    table.add_column("Notes", width=30)

    for r in results:
        assert_str = "[green]PASS[/green]" if r.assertions_passed else "[red]FAIL[/red]"
        if r.error:
            assert_str = "[red]ERROR[/red]"
        scores = r.judge_scores or {}
        g = str(scores.get("groundedness", "—"))
        t = str(scores.get("tone", "—"))
        q = str(scores.get("qualifying", "—"))
        e = str(scores.get("escalation", "—"))

        failed = [a.name for a in r.assertions if not a.passed]
        notes_parts = []
        if failed:
            notes_parts.append(f"FAIL: {', '.join(failed)}")
        if r.error:
            notes_parts.append(r.error[:40])
        elif scores.get("notes"):
            notes_parts.append(scores["notes"][:40])
        notes = " | ".join(notes_parts)

        table.add_row(
            r.scenario_id,
            r.category,
            assert_str,
            g, t, q, e,
            ", ".join(r.tool_calls_made[:5]),
            notes,
        )

    console.print(table)
    console.print()
    console.print("[dim]G=groundedness T=tone Q=qualifying E=escalation (1-5 from LLM judge)[/dim]")
    console.print()

    # Summary
    total = len(results)
    passed = sum(1 for r in results if r.assertions_passed and not r.error)
    errors = sum(1 for r in results if r.error)

    console.print(f"[bold]Assertion pass rate:[/bold] {passed}/{total} ({100*passed//total}%)")
    if errors:
        console.print(f"[red]Errors (likely quota/API):[/red] {errors}/{total}")

    # Adversarial groundedness category specifics
    adv = [r for r in results if r.category == "adversarial_groundedness"]
    if adv:
        adv_passed = sum(1 for r in adv if r.assertions_passed and not r.error)
        hallucination_rate = len(adv) - adv_passed
        console.print(
            f"[bold]Adversarial groundedness:[/bold] {adv_passed}/{len(adv)} passed — "
            f"hallucination rate: {hallucination_rate}/{len(adv)} "
            f"({'0%' if hallucination_rate == 0 else f'{100*hallucination_rate//len(adv)}%'})"
        )

        # Cosine score distribution for threshold tuning
        all_cosines = [s for r in adv for s in r.cosine_scores]
        if all_cosines:
            avg = sum(all_cosines) / len(all_cosines)
            mn = min(all_cosines)
            mx = max(all_cosines)
            console.print(
                f"[dim]Adversarial search cosine scores — "
                f"min: {mn:.3f}, avg: {avg:.3f}, max: {mx:.3f}[/dim]"
            )

    # Judge averages (if any)
    judged = [r for r in results if r.judge_scores]
    if judged:
        dims = ["groundedness", "tone", "qualifying", "escalation"]
        avgs = {d: sum(r.judge_scores.get(d, 0) for r in judged) / len(judged) for d in dims}
        console.print(
            f"[bold]Judge averages ({len(judged)} scenarios):[/bold] "
            + "  ".join(f"{d}={avgs[d]:.1f}" for d in dims)
        )


# ── Main ──────────────────────────────────────────────────────────────────────


async def main(
    skip_judge: bool,
    category_filter: str | None,
    id_filter: str | None,
    out_path: str | None,
) -> None:
    scenarios = load_scenarios(DATASETS_DIR, category_filter, id_filter)
    if not scenarios:
        console.print("[red]No scenarios found matching filters.[/red]")
        sys.exit(1)

    console.print(f"Running {len(scenarios)} scenario(s)...")
    results: list[ScenarioResult] = []
    for sc in scenarios:
        console.print(f"  [{sc['category']}] {sc['id']}: {sc['description'][:60]}...")
        result = await run_scenario(sc, skip_judge=skip_judge)
        results.append(result)

    print_report(results)

    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(
                [asdict(r) for r in results],
                f,
                indent=2,
                default=str,
            )
        console.print(f"\nResults saved to {out_path}")


def main_sync() -> None:
    parser = argparse.ArgumentParser(description="Run LeadAgent evals")
    parser.add_argument(
        "--skip-judge",
        action="store_true",
        help="Skip LLM judge (deterministic assertions only — no API calls)",
    )
    parser.add_argument("--category", default=None, help="Filter by category name")
    parser.add_argument("--id", default=None, help="Run a single scenario by ID")
    parser.add_argument("--out", default=None, help="Save results to a JSON file")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main(args.skip_judge, args.category, args.id, args.out))


if __name__ == "__main__":
    main_sync()
