from __future__ import annotations

import argparse
from pathlib import Path

from forge.builder import Builder
from forge.config import RunConfig
from forge.examiner import Examiner
from forge.loop import solve


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
    args = parser.parse_args(argv)

    goal_dir = Path(args.goal_dir)
    config = RunConfig.from_yaml(args.config) if args.config else RunConfig()
    write_tests = not args.no_regenerate

    examiner = build_examiner(config) if write_tests else _NullExaminer()

    if write_tests and not args.yes:
        ex = examiner.write_tests((goal_dir / "goal.md").read_text())
        print("=== proposed test plan ===")
        print(ex.suite.test_plan)
        if input("Approve and start the build loop? [y/N] ").strip().lower() != "y":
            print("Aborted.")
            return 1
        # Re-use the just-written suite by persisting it and switching off regeneration.
        from forge.examiner import split_suite
        from forge.loop import _write_tests
        visible, held = split_suite(ex.suite.tests, config.holdout_fraction)
        _write_tests(goal_dir / "tests_frozen", visible)
        _write_tests(goal_dir / "tests_holdout", held)
        write_tests = False

    builder = Builder(model=config.builder_model)
    result = solve(goal_dir, config, examiner, builder, write_tests=write_tests)

    print(f"\nresult: success={result.success} reason={result.reason} "
          f"score={result.best_score:.2f} iterations={result.iterations}")
    print(f"best solution: {result.best_dir}")
    return 0 if result.success else 2


class _NullExaminer:
    def write_tests(self, goal):  # pragma: no cover - never called when write_tests=False
        raise RuntimeError("Examiner should not run when tests are reused")


if __name__ == "__main__":
    raise SystemExit(main())
