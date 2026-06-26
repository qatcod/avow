from __future__ import annotations

import argparse
from pathlib import Path

from forge.builder import Builder
from forge.config import RunConfig
from forge.examiner import Examiner
from forge.loop import solve


def _cmd_mutate(args) -> int:
    from forge.mutation import run_mutation_testing

    config = RunConfig.from_yaml(args.config) if args.config else RunConfig()
    client = model = None
    llm_n = 0
    if args.llm:
        import anthropic
        client = anthropic.Anthropic()
        model = config.mutation_model
        llm_n = config.llm_mutants_n

    result = run_mutation_testing(
        Path(args.solution_dir), Path(args.tests_dir), config.test_command,
        max_ast_mutants=config.max_ast_mutants, llm_n=llm_n,
        timeout=config.test_timeout_seconds, client=client, model=model, goal="",
    )
    if not result.baseline_green:
        print("suite is not green on the unmutated solution — cannot score "
              "(fix the suite or the solution first)")
        return 1
    print(f"mutation score: {result.score:.2f}  ({result.killed}/{result.total} killed)")
    if result.survivors:
        print(f"\n{result.survived} survivors (potential test gaps):")
        for s in result.survivors:
            print(f"  - [{s.origin}] {s.file}: {s.description}")
    return 0


def _cmd_intent_check(args) -> int:
    import anthropic
    from forge.backtranslation import run_intent_check

    config = RunConfig.from_yaml(args.config) if args.config else RunConfig()
    goal = Path(args.goal_file).read_text(encoding="utf-8")
    result = run_intent_check(goal, Path(args.tests_dir),
                              anthropic.Anthropic(), config.backtranslation_model)
    print(f"intent match: {result.score:.2f}")
    print(f"\ninferred goal (from the tests alone):\n{result.inferred_goal}")
    if result.divergences:
        print("\ndivergences (goal vs what the tests actually pin down):")
        for d in result.divergences:
            print(f"  - {d}")
    return 0


def build_examiner(config: RunConfig) -> Examiner:
    import anthropic  # imported lazily so unit tests don't need network/creds
    return Examiner(anthropic.Anthropic(), model=config.examiner_model)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="forge")
    sub = parser.add_subparsers(dest="command", required=True)
    solve_p = sub.add_parser("solve", help="run the build-and-improve loop on a goal dir")
    solve_p.add_argument("goal_dir")
    solve_p.add_argument("--config", default=None)
    solve_p.add_argument("--no-regenerate", action="store_true",
                         help="reuse existing tests_frozen/ instead of calling the Examiner")
    solve_p.add_argument("--yes", action="store_true",
                         help="skip the human approval gate on the generated test plan")
    mut_p = sub.add_parser("mutate", help="score a test suite's strength via mutation testing")
    mut_p.add_argument("solution_dir")
    mut_p.add_argument("tests_dir")
    mut_p.add_argument("--config", default=None)
    mut_p.add_argument("--llm", action="store_true",
                       help="also generate a few cross-model LLM mutants")
    ic_p = sub.add_parser("intent-check",
                          help="back-translate a test suite and score how well it matches a goal")
    ic_p.add_argument("goal_file")
    ic_p.add_argument("tests_dir")
    ic_p.add_argument("--config", default=None)
    args = parser.parse_args(argv)

    if args.command == "mutate":
        return _cmd_mutate(args)

    if args.command == "intent-check":
        return _cmd_intent_check(args)

    goal_dir = Path(args.goal_dir)
    config = RunConfig.from_yaml(args.config) if args.config else RunConfig()
    write_tests = not args.no_regenerate
    examiner = build_examiner(config) if write_tests else _NullExaminer()

    confirm = None
    if write_tests and not args.yes:
        def confirm(plan: str) -> bool:
            print("=== proposed test plan ===")
            print(plan)
            return input("Approve and start the build loop? [y/N] ").strip().lower() == "y"

    builder = Builder(model=config.builder_model, timeout=config.builder_timeout_seconds)
    result = solve(goal_dir, config, examiner, builder, write_tests=write_tests, confirm=confirm)

    if result.reason == "aborted":
        print("Aborted.")
        return 1
    print(f"\nresult: success={result.success} reason={result.reason} "
          f"score={result.best_score:.2f} iterations={result.iterations}")
    if result.best_dir is not None:
        print(f"best solution: {result.best_dir}")
    return 0 if result.success else 2


class _NullExaminer:
    def write_tests(self, goal):  # pragma: no cover - never called when write_tests=False
        raise RuntimeError("Examiner should not run when tests are reused")


if __name__ == "__main__":
    raise SystemExit(main())
