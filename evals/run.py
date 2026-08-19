"""The eval runner: execute golden cases, judge, record, GATE.

Run it from the project root:

    python -m evals.run --suite all --note "why this run"
    python -m evals.run --suite match --update-baseline

What one run does, in order:

1. Tags itself: a unique run id goes into the gateway's ContextVar, so
   EVERY AI call this run causes — agents, sub-agents, judges — lands in
   agent_runs carrying this id. The run's exact cost is then one SQL sum.
2. Executes each golden case through the SAME pure cores production
   uses (score_match, generate_tailored_content) — eval drift is
   structurally impossible because there is no eval-only code path.
3. Judges each output: deterministic checks always; AI judges only in
   real mode (a fake judge approving a fake answer proves nothing —
   fake-mode runs verify PLUMBING AND STRUCTURE, real-mode runs verify
   QUALITY; both honest, clearly labeled).
4. Records everything: one eval_runs row, one eval_case_results row per
   case, failures named.
5. THE GATE: compares against the committed baseline for the current
   mode. Any case that PASSED in the baseline and FAILS now is a
   regression -> exit code 1 -> Continuous Integration blocks the merge.
   Known-failing cases stay visible without blocking; NEW cases are
   allowed. --update-baseline rewrites the baseline (a reviewed,
   committed file — moving the quality bar is a Pull Request, never an
   accident).
"""

import argparse
import asyncio
import json
import pathlib
import sys
import uuid

from sqlalchemy import func as sa_func
from sqlalchemy import select

from app.agents.tailor import generate_tailored_content
from app.config import settings
from app.db import session_factory
from app.llm import current_run_id
from app.matching import score_match
from app.models import AgentRun, EvalCaseResult, EvalRun
from evals.cases import load_match_cases, load_tailoring_cases
from evals.checks import (
    check_match,
    check_pair_ranking,
    check_tailoring,
    judge_match,
    judge_tailoring,
)

BASELINE_PATH = pathlib.Path(__file__).parent / "baseline.json"


def mode_name() -> str:
    return "fake" if settings.fake_ai else "real"


async def run_match_suite() -> dict[str, list]:
    """Returns {case_id: [checks]} including the pairwise ranking case."""
    cases = load_match_cases()
    results: dict[str, list] = {}
    analyses = {}
    for case in cases:
        analysis = await score_match(
            case.profile, case.job_title, case.job_company, case.job_description
        )
        analyses[case.case_id] = (case, analysis)
        checks = check_match(case, analysis)
        if not settings.fake_ai:
            checks += await judge_match(case, analysis)
        results[case.case_id] = checks

    # The relative checks: every (pair_key) strong/weak pair.
    pairs: dict[str, dict] = {}
    for case, analysis in analyses.values():
        if case.pair_key and case.pair_role in ("strong", "weak"):
            pairs.setdefault(case.pair_key, {})[case.pair_role] = (case, analysis)
    for key, pair in pairs.items():
        if "strong" in pair and "weak" in pair:
            check = check_pair_ranking(*pair["strong"], *pair["weak"])
            results[f"match/ranking_{key}"] = [check]
    return results


async def run_tailoring_suite() -> dict[str, list]:
    results: dict[str, list] = {}
    for case in load_tailoring_cases():
        content = await generate_tailored_content(
            case.profile,
            case.raw_resume_text,
            case.job_title,
            case.job_company,
            case.job_description,
        )
        checks = check_tailoring(case, content)
        if not settings.fake_ai:
            checks += await judge_tailoring(case, content)
        results[case.case_id] = checks
    return results


async def persist_run(
    run_id: str, suite: str, note: str | None, results: dict[str, list]
) -> tuple[int, int, float]:
    total = len(results)
    passed = sum(1 for checks in results.values() if all(ok for _, ok, _ in checks))
    async with session_factory() as session:
        cost = (
            await session.execute(
                select(sa_func.coalesce(sa_func.sum(AgentRun.cost_usd), 0.0)).where(
                    AgentRun.run_id == run_id
                )
            )
        ).scalar_one()
        session.add(
            EvalRun(
                id=run_id,
                suite=suite,
                note=note,
                fake_mode=settings.fake_ai,
                total=total,
                passed=passed,
                pass_rate=passed / total if total else 0.0,
                cost_usd=float(cost),
            )
        )
        # The case rows reference the run row: flush the parent to the
        # database BEFORE the children are added, or the insert order can
        # violate the foreign key. (Found by this file's very first run.)
        await session.flush()
        for case_id, checks in results.items():
            failures = [
                {"check": name, "detail": detail}
                for name, ok, detail in checks
                if not ok
            ]
            session.add(
                EvalCaseResult(
                    run_id=run_id,
                    case_id=case_id,
                    agent=case_id.split("/")[0],
                    passed=not failures,
                    failures=failures or None,
                )
            )
        await session.commit()
    return total, passed, float(cost)


def load_baseline() -> dict:
    if BASELINE_PATH.exists():
        return json.loads(BASELINE_PATH.read_text())
    return {}


def apply_gate(results: dict[str, list], baseline: dict) -> tuple[list[str], bool]:
    """Returns (regressions, gate_available). A regression is a case that
    the committed baseline says PASSED (in this mode) and now fails."""
    mode_baseline = baseline.get(mode_name())
    if mode_baseline is None:
        return [], False
    regressions = [
        case_id
        for case_id, checks in results.items()
        if mode_baseline.get(case_id) is True and not all(ok for _, ok, _ in checks)
    ]
    return regressions, True


def update_baseline(results: dict[str, list]) -> None:
    baseline = load_baseline()
    baseline[mode_name()] = {
        case_id: all(ok for _, ok, _ in checks)
        for case_id, checks in results.items()
    }
    BASELINE_PATH.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run the evaluation suites.")
    parser.add_argument("--suite", choices=["match", "tailoring", "all"], default="all")
    parser.add_argument("--note", default=None)
    parser.add_argument("--update-baseline", action="store_true")
    args = parser.parse_args()

    run_id = uuid.uuid4().hex[:12]
    token = current_run_id.set(run_id)
    try:
        results: dict[str, list] = {}
        if args.suite in ("match", "all"):
            results |= await run_match_suite()
        if args.suite in ("tailoring", "all"):
            results |= await run_tailoring_suite()
        total, passed, cost = await persist_run(run_id, args.suite, args.note, results)
    finally:
        current_run_id.reset(token)

    print(f"\neval run {run_id}  [{mode_name()} mode]  suite={args.suite}")
    print(f"cases: {passed}/{total} passed   cost: ${cost:.4f}\n")
    for case_id, checks in sorted(results.items()):
        ok = all(passed_ for _, passed_, _ in checks)
        print(f"  {'PASS' if ok else 'FAIL'}  {case_id}")
        for name, passed_, detail in checks:
            if not passed_:
                print(f"          failed check: {name} — {detail}")

    if args.update_baseline:
        update_baseline(results)
        print(f"\nbaseline updated for {mode_name()} mode: {BASELINE_PATH}")
        return 0

    regressions, gate_available = apply_gate(results, load_baseline())
    if not gate_available:
        print(
            f"\nNo {mode_name()}-mode baseline committed yet — the gate cannot "
            "judge this run. Review the results above, then run with "
            "--update-baseline to set the bar."
        )
        return 0
    if regressions:
        print("\nREGRESSION GATE: FAILED — these cases passed in the baseline "
              "and fail now:")
        for case_id in regressions:
            print(f"  - {case_id}")
        return 1
    print("\nregression gate: clean (no previously-passing case fails)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
