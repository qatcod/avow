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


def _cmd_verify(args) -> int:
    import anthropic
    from forge.mutation import run_mutation_testing
    from forge.backtranslation import run_intent_check
    from forge.confidence import aggregate_confidence

    config = RunConfig.from_yaml(args.config) if args.config else RunConfig()
    client = anthropic.Anthropic()
    goal = Path(args.goal_file).read_text(encoding="utf-8")

    mr = run_mutation_testing(
        Path(args.solution_dir), Path(args.tests_dir), config.test_command,
        max_ast_mutants=config.max_ast_mutants,
        llm_n=(config.llm_mutants_n if args.llm else 0),
        timeout=config.test_timeout_seconds,
        client=(client if args.llm else None), model=config.mutation_model, goal=goal,
    )
    ir = run_intent_check(goal, Path(args.tests_dir), client, config.backtranslation_model)

    mutation_signal = mr.score if mr.baseline_green else None
    conf = aggregate_confidence(
        {"mutation": mutation_signal, "intent": ir.score}, config.confidence_weights)

    if not mr.baseline_green:
        print("warning: suite is not green on the unmutated solution — mutation signal omitted")
    print(f"confidence: {conf.score:.2f}")
    print("breakdown:")
    for k, v in conf.breakdown.items():
        print(f"  {k}: {v:.2f}  (weight {conf.weights_used[k]:.2f})")
    if mr.baseline_green:
        print(f"\nmutation: {mr.killed}/{mr.total} killed, {mr.survived} survivors")
    print(f"intent inferred goal: {ir.inferred_goal}")
    if ir.divergences:
        print("intent divergences:")
        for d in ir.divergences:
            print(f"  - {d}")
    return 0


def _cmd_propertize(args) -> int:
    import anthropic
    from forge.properties import generate_property_tests

    config = RunConfig.from_yaml(args.config) if args.config else RunConfig()
    goal = Path(args.goal_file).read_text(encoding="utf-8")
    props, _in, _out = generate_property_tests(
        goal, anthropic.Anthropic(), config.property_model, config.property_tests_n)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for tf in props:
        name = Path(tf.path).name
        (out_dir / name).write_text(tf.content, encoding="utf-8")
        print(f"wrote {name}")
    print(f"\n{len(props)} property test file(s) written to {out_dir}")
    return 0


def _cmd_improve(args) -> int:
    from forge.improve import improve

    config = RunConfig.from_yaml(args.config) if args.config else RunConfig()
    examiner = build_examiner(config)
    builder = Builder(model=config.builder_model, timeout=config.builder_timeout_seconds)

    verify_client = None
    if not args.no_llm_verify:
        import anthropic
        verify_client = anthropic.Anthropic()

    result = improve(Path(args.goal_dir), config, examiner, builder,
                     ideator_client=verify_client, intent_client=verify_client,
                     property_client=verify_client)

    print(f"result: success={result.success} expansions={result.expansions}")
    for i, r in enumerate(result.rounds):
        print(f"  round {i}: success={r.success} reason={r.reason} confidence={r.confidence}")
    return 0 if result.success else 2


def _cmd_oracle(args) -> int:
    import anthropic
    from forge.oracle import run_oracle_check

    config = RunConfig.from_yaml(args.config) if args.config else RunConfig()
    goal = Path(args.goal_file).read_text(encoding="utf-8")
    res = run_oracle_check(Path(args.solution_dir), goal, anthropic.Anthropic(),
                           config.oracle_model, config.test_command, config.test_timeout_seconds)
    print(f"oracle agreement: {res.agreement}")
    if res.counterexample:
        print(f"counterexample:\n{res.counterexample}")
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
    solve_p.add_argument("--no-llm-verify", action="store_true",
                         help="skip the LLM verification hooks (intent check + property tests) for a cheaper run")
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
    ver_p = sub.add_parser("verify",
                           help="run all verifiers on an artifact and report a calibrated confidence")
    ver_p.add_argument("solution_dir")
    ver_p.add_argument("tests_dir")
    ver_p.add_argument("goal_file")
    ver_p.add_argument("--config", default=None)
    ver_p.add_argument("--llm", action="store_true", help="also use cross-model LLM mutants")
    prop_p = sub.add_parser("propertize",
                            help="generate Hypothesis property/metamorphic tests for a goal")
    prop_p.add_argument("goal_file")
    prop_p.add_argument("out_dir")
    prop_p.add_argument("--config", default=None)
    improve_p = sub.add_parser("improve",
                               help="self-improvement loop: converge, then propose & build next features")
    improve_p.add_argument("goal_dir")
    improve_p.add_argument("--config", default=None)
    improve_p.add_argument("--no-llm-verify", action="store_true")
    oracle_p = sub.add_parser("oracle",
                              help="differential-test a solution against an independent reference impl")
    oracle_p.add_argument("solution_dir")
    oracle_p.add_argument("goal_file")
    oracle_p.add_argument("--config", default=None)
    args = parser.parse_args(argv)

    if args.command == "mutate":
        return _cmd_mutate(args)

    if args.command == "intent-check":
        return _cmd_intent_check(args)

    if args.command == "verify":
        return _cmd_verify(args)

    if args.command == "propertize":
        return _cmd_propertize(args)

    if args.command == "improve":
        return _cmd_improve(args)

    if args.command == "oracle":
        return _cmd_oracle(args)

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

    verify_client = None
    if write_tests and not args.no_llm_verify:
        import anthropic
        verify_client = anthropic.Anthropic()
    builder = Builder(model=config.builder_model, timeout=config.builder_timeout_seconds)
    result = solve(goal_dir, config, examiner, builder, write_tests=write_tests, confirm=confirm,
                   intent_client=verify_client, property_client=verify_client)

    if result.reason == "aborted":
        print("Aborted.")
        return 1
    print(f"\nresult: success={result.success} reason={result.reason} "
          f"score={result.best_score:.2f} iterations={result.iterations}")
    if result.confidence is not None:
        print(f"confidence: {result.confidence:.2f}")
        for _k, _v in result.confidence_breakdown.items():
            print(f"  {_k}: {_v:.2f}")
    if result.best_dir is not None:
        print(f"best solution: {result.best_dir}")
    if result.success:
        return 0
    return 3 if result.reason == "low_confidence" else 2


class _NullExaminer:
    def write_tests(self, goal):  # pragma: no cover - never called when write_tests=False
        raise RuntimeError("Examiner should not run when tests are reused")


if __name__ == "__main__":
    raise SystemExit(main())
