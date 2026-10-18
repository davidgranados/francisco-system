"""Run the bot's eval set against the API and print one column per model.

    uv run python -m evals.run --model claude-haiku-5-5 --model claude-sonnet-5-5 --repeat 3
    uv run python -m evals.run --golden      # offline: a scripted client, no API key needed

Needs Postgres (docker compose up -d) and ANTHROPIC_API_KEY unless --golden.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic

from app.agent.options import request_options
from evals.cases import load_cases, problems
from evals.golden import GoldenClient
from evals.harness import (
    EvalDatabases,
    RunResult,
    report_table,
    run_all,
    started_at,
    summarize,
)

RESULTS = Path(__file__).with_name("resultados")
DEFAULT_URL = "postgresql+asyncpg://francisco:francisco@localhost:5432/francisco_eval"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m evals.run", description=__doc__)
    parser.add_argument("--model", action="append", help="repetible; por defecto Haiku 5.5")
    parser.add_argument("--case", action="append", help="id de un caso; repetible")
    parser.add_argument("--category", action="append", help="solo esta categoría; repetible")
    parser.add_argument("--repeat", type=int, default=1, help="corridas por caso y modelo")
    parser.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--thinking", choices=["adaptive", "off"], default="adaptive")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.9,
        help="sale con código 1 si algún modelo pasa menos de esta fracción de corridas",
    )
    parser.add_argument("--golden", action="store_true", help="cliente guionado, sin red")
    parser.add_argument("--database-url", default=os.environ.get("EVAL_DATABASE_URL", DEFAULT_URL))
    return parser.parse_args(argv)


def _progress(result: RunResult) -> None:
    mark = "ok " if result.passed else "MAL"
    print(f"{mark} {result.model} {result.case_id} #{result.repeat}", flush=True)
    for failure in result.failures:
        print(f"      {failure}", flush=True)


async def main(argv: list[str]) -> int:
    args = parse_args(argv)
    cases = load_cases()
    found = problems(cases)
    if found:
        print("\n".join(found), file=sys.stderr)
        return 2
    if args.case:
        cases = [case for case in cases if case.id in args.case]
    if args.category:
        cases = [case for case in cases if case.categoria in args.category]
    if not cases:
        print("Ningún caso coincide.", file=sys.stderr)
        return 2
    models = args.model or ["claude-haiku-5-5"]
    if args.golden:

        def client_for(case: Any) -> Any:
            return GoldenClient(case)

    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("Falta ANTHROPIC_API_KEY (o use --golden).", file=sys.stderr)
            return 2
        shared = AsyncAnthropic(max_retries=4)

        def client_for(case: Any) -> Any:
            return shared

    results = await run_all(
        cases,
        models,
        args.repeat,
        client_for,
        lambda model: request_options(model, args.effort, args.thinking),
        EvalDatabases(args.database_url),
        concurrency=args.concurrency,
        on_result=_progress,
    )
    summary = summarize(results)
    print()
    print(report_table(summary))
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"{started_at()}{'-golden' if args.golden else ''}.json"
    report = {
        "config": {
            "models": models,
            "repeat": args.repeat,
            "effort": args.effort,
            "thinking": args.thinking,
            "golden": args.golden,
            "cases": [case.id for case in cases],
            "options": {
                model: request_options(model, args.effort, args.thinking) for model in models
            },
        },
        "summary": summary,
        "runs": [result.as_json() for result in results],
    }
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(f"\nReporte: {path}")
    below = [m for m, s in summary.items() if s["pass_rate"] < args.threshold]
    if below:
        print(f"Por debajo del umbral {args.threshold:.0%}: {', '.join(below)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
