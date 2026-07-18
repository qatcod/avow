from __future__ import annotations

import argparse
from pathlib import Path

from avow.builder import Builder
from avow.config import RunConfig
from avow.examiner import Examiner
from avow.loop import solve


def _cmd_mutate(args) -> int:
    from avow.mutation import run_mutation_testing

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
            loc = f"{s.file}:{s.line}" if s.line else s.file
            print(f"  - [{s.origin}] {loc}: {s.description}")
    return 0


def _cmd_intent_check(args) -> int:
    import anthropic
    from avow.backtranslation import run_intent_check

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
    from avow.mutation import run_mutation_testing
    from avow.backtranslation import run_intent_check
    from avow.confidence import aggregate_confidence

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
    from avow.properties import generate_property_tests

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
    from avow.improve import improve

    config = RunConfig.from_yaml(args.config) if args.config else RunConfig()
    examiner = build_examiner(config)
    builder = Builder(model=config.builder_model, timeout=config.builder_timeout_seconds)

    verify_client = None
    if not args.no_llm_verify:
        import anthropic
        verify_client = anthropic.Anthropic()

    result = improve(Path(args.goal_dir), config, examiner, builder,
                     ideator_client=verify_client, intent_client=verify_client,
                     property_client=verify_client, oracle_client=verify_client)

    print(f"result: success={result.success} expansions={result.expansions}")
    for i, r in enumerate(result.rounds):
        print(f"  round {i}: success={r.success} reason={r.reason} confidence={r.confidence}")
    return 0 if result.success else 2


def _cmd_oracle(args) -> int:
    import anthropic
    from avow.oracle import run_oracle_check

    config = RunConfig.from_yaml(args.config) if args.config else RunConfig()
    goal = Path(args.goal_file).read_text(encoding="utf-8")
    res = run_oracle_check(Path(args.solution_dir), goal, anthropic.Anthropic(),
                           config.oracle_model, config.test_command, config.test_timeout_seconds)
    print(f"oracle agreement: {res.agreement}")
    if res.counterexample:
        print(f"counterexample:\n{res.counterexample}")
    return 1 if res.agreement == 0.0 else 0


def _cmd_harden(args) -> int:
    from avow.harden import harden

    config = RunConfig.from_yaml(args.config) if args.config else RunConfig()
    examiner = build_examiner(config)
    builder = Builder(model=config.builder_model, timeout=config.builder_timeout_seconds)

    verify_client = None
    if not args.no_llm_verify:
        import anthropic
        verify_client = anthropic.Anthropic()

    result = harden(Path(args.goal_dir), config, examiner, builder,
                    intent_client=verify_client, property_client=verify_client,
                    oracle_client=verify_client)

    print(f"result: success={result.success} adversarial_rounds={result.rounds_run}")
    for i, r in enumerate(result.rounds):
        print(f"  round {i}: success={r.success} reason={r.reason} confidence={r.confidence}")
    return 0 if result.success else 2


def _anthropic(config):
    # Long multi-call verbs raise the SDK's default retry budget so a transient network blip over a
    # long run is absorbed rather than aborting the whole run.
    import anthropic
    return anthropic.Anthropic(max_retries=config.llm_max_retries)


def _cmd_survive(args) -> int:
    from avow.survive import survive

    config = RunConfig.from_yaml(args.config) if args.config else RunConfig()
    examiner = build_examiner(config)
    builder = Builder(model=config.builder_model, timeout=config.builder_timeout_seconds)
    verify_client = None
    if not args.no_llm_verify:
        verify_client = _anthropic(config)
    if args.graveyard:
        config.graveyard_path = args.graveyard
    result = survive(Path(args.goal_dir), config, examiner, builder,
                     gauntlet_client=verify_client, coroner_client=verify_client,
                     intent_client=verify_client, property_client=verify_client,
                     oracle_client=verify_client)
    print(f"result: status={result.status} gauntlet_rounds={result.rounds}")
    if result.status == "died" and result.death_counterexample is not None:
        print(f"  killed by counterexample: {result.death_counterexample.input_repr}")
    print("note: 'verified_survivor' means it survived a K-reference execution gauntlet, "
          "not a proof of correctness.")
    return 0 if result.status in ("verified_survivor", "unverified") else 2


def _cmd_graveyard(args) -> int:
    from avow.graveyard import load, default_graveyard_path

    path = args.graveyard or str(default_graveyard_path())
    patterns = load(path)
    print(f"graveyard: {path}  ({len(patterns)} patterns)")
    for p in patterns:
        print(f"  [{p.category}] {p.description}")
    return 0


def _cmd_gauntlet(args) -> int:
    from avow.gauntlet import run_gauntlet

    config = RunConfig.from_yaml(args.config) if args.config else RunConfig()
    goal = Path(args.goal_file).read_text(encoding="utf-8")
    g = run_gauntlet(Path(args.solution_dir), goal, _anthropic(config), config.gauntlet_model,
                     config.test_command, k=config.gauntlet_references_k,
                     examples=config.gauntlet_examples, timeout=config.test_timeout_seconds)
    if g.survived:
        print(f"VERIFIED SURVIVOR — agreed with {g.references_ok}/{g.references_total} independent "
              f"references across the fuzzed space (survived the gauntlet; not a proof of correctness)")
        return 0
    print("KILLED — a majority of independent references diverge from this solution.")
    print(f"  counterexample: {g.counterexample.input_repr}")
    return 2


def _cmd_population(args) -> int:
    from avow.population import population_solve, hybrid_solve

    config = RunConfig.from_yaml(args.config) if args.config else RunConfig()
    examiner = build_examiner(config)
    builder = Builder(model=config.builder_model, timeout=config.builder_timeout_seconds)

    verify_client = None
    if not args.no_llm_verify:
        import anthropic
        verify_client = anthropic.Anthropic()

    run = hybrid_solve if args.hybrid else population_solve
    result = run(Path(args.goal_dir), config, examiner, builder,
                 intent_client=verify_client, property_client=verify_client,
                 oracle_client=verify_client)

    print(f"result: success={result.success} winner=candidate {result.winner_index} "
          f"({len(result.candidates)} candidates)")
    for c in result.candidates:
        print(f"  candidate {c.index}: success={c.result.success} reason={c.result.reason} "
              f"confidence={c.result.confidence}")
    return 0 if result.success else 2


def _cmd_supervise(args) -> int:
    import json
    from types import SimpleNamespace
    import anthropic
    from avow.supervisor import review_trajectory

    config = RunConfig.from_yaml(args.config) if args.config else RunConfig()
    goal = Path(args.goal_file).read_text(encoding="utf-8")
    history = []
    for line in Path(args.run_jsonl).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        history.append(SimpleNamespace(
            iteration=d.get("iteration", 0), score=d.get("score", 0.0),
            is_green=d.get("is_green", False), plan=d.get("plan", ""),
            failing=d.get("failing", [])))

    verdict, _in, _out = review_trajectory(goal, history, anthropic.Anthropic(), config.supervisor_model)
    print(f"supervisor recommendation: {verdict.recommendation} (escalate={verdict.escalate})")
    print(f"assessment: {verdict.assessment}")
    return 0


def _cmd_adjudicate(args) -> int:
    import anthropic
    from avow.adjudicator import adjudicate_failures
    from avow.runner import Runner

    config = RunConfig.from_yaml(args.config) if args.config else RunConfig()
    goal = Path(args.goal_file).read_text(encoding="utf-8")
    result = Runner(Path(args.solution_dir), Path(args.tests_dir), config.test_command,
                    timeout=config.test_timeout_seconds).run()
    if not result.failures:
        print("no failing tests — nothing to adjudicate")
        return 0
    failing = [f.nodeid for f in result.failures]
    adj = adjudicate_failures(goal, Path(args.tests_dir), failing, anthropic.Anthropic(),
                              config.adjudicate_model, config.test_command,
                              k=config.adjudicate_references_k, timeout=config.test_timeout_seconds)
    for v in adj.verdicts:
        passed = v.references_total - v.references_failed
        if v.verdict == "test_bug":
            print(f"  {v.test_id}: TEST BUG — {v.references_failed}/{v.references_total} "
                  f"independent references ALSO fail it (no correct implementation passes it)")
        elif v.verdict == "solution_bug":
            print(f"  {v.test_id}: SOLUTION BUG — {passed}/{v.references_total} "
                  f"independent references pass it (the solution is the outlier)")
        else:
            print(f"  {v.test_id}: INCONCLUSIVE — references split "
                  f"({v.references_failed} fail / {passed} pass{'' if v.references_total else ', none usable'})")
    suspected = [v.test_id for v in adj.verdicts if v.verdict == "test_bug"]
    if suspected:
        print(f"\nSuspected Examiner-authored bad test(s): {suspected}")
    return 0


def _cmd_check(args) -> int:
    from avow.checks import run_checks

    config = RunConfig.from_yaml(args.config) if args.config else RunConfig()
    if not config.checks:
        print("no checks configured (add a `checks:` list to your config)")
        return 0
    results = run_checks(Path(args.solution_dir), config.checks, config.test_timeout_seconds,
                         strip_config=config.strip_check_config)
    for c in results:
        line = f"  {c.name}: {'PASS' if c.passed else 'FAIL'}"
        if not c.passed and c.detail:
            line += f"  — {c.detail.strip().splitlines()[0][:140]}"
        print(line)
    return 0 if all(c.passed for c in results) else 2


def _cmd_report(args) -> int:
    from collections import defaultdict
    from avow.report import run_report

    config = RunConfig.from_yaml(args.config) if args.config else RunConfig()
    rep = run_report(Path(args.repo), config, max_ast_mutants=args.max_mutants,
                     source_override=args.source, tests_override=args.tests)
    print(f"repo: {args.repo}")
    print(f"  source modules: {len(rep.source_files)}   test files: {len(rep.test_files)}")
    if not rep.baseline_green:
        print(f"  {rep.detail}")
        return 1
    print(f"  suite strength (mutation): {rep.score:.2f}  ({rep.killed}/{rep.total} mutants killed)")
    if rep.survivors:
        by_file = defaultdict(list)
        for s in rep.survivors:
            by_file[s.file].append(s)
        print(f"\n  {len(rep.survivors)} surviving mutants — code changes NO test caught (candidate gaps):")
        for f in sorted(by_file):
            print(f"    {f}")
            for s in by_file[f]:
                loc = f"line {s.line}" if s.line else "?"
                print(f"      {loc}: {s.description}")
    else:
        print("  no surviving mutants — the suite killed every fault Avow injected")
    return 0


def _stub_coroner():
    from types import SimpleNamespace
    from avow.graveyard import AttackPattern

    class _C:
        @property
        def messages(self):
            return self

        def parse(self, *, output_format, **kwargs):
            po = AttackPattern(category="numeric-boundary",
                               description="probe where a shorter numeric field meets a longer one",
                               origin_goal="", example_input="x")
            return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    return _C()


def _cmd_calibrate_gauntlet(args) -> int:
    from avow.calibration_gauntlet import run_calibration_proof, ProofClients
    from avow.calibration_benchmark import (DEFAULT_GOALS, FAMILY_GOALS,
                                            make_scoring_stub, make_mining_stub)

    config = RunConfig.from_yaml(args.config) if args.config else RunConfig()
    if args.llm:
        client = _anthropic(config)
        goals = DEFAULT_GOALS + FAMILY_GOALS
        clients = ProofClients(scoring_for=lambda g: client, mining_for=lambda g: client,
                               coroner=client, oracle=client)
        label = f"n={sum(len(g.variants) for g in goals)}, LLM references, single run"
    else:
        goals = FAMILY_GOALS   # the stubs only cover the family; DEFAULT_GOALS need real references
        clients = ProofClients(scoring_for=lambda g: make_scoring_stub(g.name),
                               mining_for=lambda g: make_mining_stub(g.name),
                               coroner=_stub_coroner(), oracle=None)
        label = "STUB MODE -- deterministic mechanism demonstration, not real references"

    proof = run_calibration_proof(goals, lambda g: "bug_lexical", config, clients,
                                  min_n=8, use_oracle=args.llm, with_seed=args.seed)
    print(f"calibration proof ({label}):")
    print(proof.honesty(min_n=8))
    print("note: 'survived' means it agreed with independent references across a fuzzed space -- "
          "not a proof of correctness.")
    return 0


def _cmd_calibrate(args) -> int:
    if getattr(args, "gauntlet", False):
        return _cmd_calibrate_gauntlet(args)

    from avow.calibration import run_calibration
    from avow.calibration_benchmark import DEFAULT_GOALS

    config = RunConfig.from_yaml(args.config) if args.config else RunConfig()
    oracle_client = None
    if args.llm:
        oracle_client = _anthropic(config)   # multi-goal sweep -> same transient-failure exposure
    report = run_calibration(DEFAULT_GOALS, config, oracle_client=oracle_client)
    use_oracle = args.llm

    print(f"{'goal':11} {'variant':17} {'green':6} {'conf':6} {'correct':8}")
    for r in report.rows:
        c = "-" if r.confidence is None else f"{r.confidence:.2f}"
        print(f"{r.goal:11} {r.variant:17} {str(r.green):6} {c:6} {str(r.correct):8}")
    print(f"\nreliability (green solutions bucketed by confidence"
          f"{', oracle floor applied' if use_oracle else ''}):")
    for (lo, hi), (corr, tot) in report.reliability(use_oracle=use_oracle):
        if tot:
            print(f"  conf [{lo:.2f},{hi:.2f}): {corr}/{tot} correct  ({corr / tot:.0%})")
    fh, t = report.false_high_confidence(use_oracle=use_oracle)
    kind = "with oracle floor" if use_oracle else "offline signals only (add --llm for the oracle)"
    print(f"\nfalse-high-confidence: {fh}/{t} trusted solutions are actually WRONG "
          f"({(fh / t * 100 if t else 0):.0f}%)  [{kind}]")
    return 0


def build_examiner(config: RunConfig) -> Examiner:
    import anthropic  # imported lazily so unit tests don't need network/creds
    return Examiner(anthropic.Anthropic(), model=config.examiner_model)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="avow")
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
    harden_p = sub.add_parser("harden",
                              help="build, then escalate the suite with adversarial tests over rounds")
    harden_p.add_argument("goal_dir")
    harden_p.add_argument("--config", default=None)
    harden_p.add_argument("--no-llm-verify", action="store_true")
    survive_p = sub.add_parser(
        "survive", help="converge, then survive a harder execution gauntlet — one counterexample kills the green and it fights back")
    survive_p.add_argument("goal_dir")
    survive_p.add_argument("--config", default=None)
    survive_p.add_argument("--no-llm-verify", action="store_true")
    survive_p.add_argument("--graveyard", default=None)
    graveyard_p = sub.add_parser("graveyard", help="list the global attack-pattern memory (what Avow has learned)")
    graveyard_p.add_argument("--graveyard", default=None)
    gauntlet_p = sub.add_parser(
        "gauntlet", help="attack an existing solution once: K independent references vs the solution over a fuzzed input space")
    gauntlet_p.add_argument("solution_dir")
    gauntlet_p.add_argument("goal_file")
    gauntlet_p.add_argument("--config", default=None)
    pop_p = sub.add_parser("population",
                           help="run N candidate solutions and let the verifier pick the winner")
    pop_p.add_argument("goal_dir")
    pop_p.add_argument("--config", default=None)
    pop_p.add_argument("--no-llm-verify", action="store_true")
    pop_p.add_argument("--hybrid", action="store_true",
                       help="run one attempt first; escalate to the population only on failure")
    sup_p = sub.add_parser("supervise",
                           help="review a recorded run's trajectory and print the Supervisor's verdict")
    sup_p.add_argument("run_jsonl")
    sup_p.add_argument("goal_file")
    sup_p.add_argument("--config", default=None)
    adj_p = sub.add_parser("adjudicate",
                           help="for a stalled build: decide (by execution) which failing tests are the Examiner's bug")
    adj_p.add_argument("solution_dir")
    adj_p.add_argument("tests_dir")
    adj_p.add_argument("goal_file")
    adj_p.add_argument("--config", default=None)
    check_p = sub.add_parser(
        "check", help="run the configured verifier checks (lint/typecheck/audit/...) on a solution")
    check_p.add_argument("solution_dir")
    check_p.add_argument("--config", default=None)
    cal_p = sub.add_parser(
        "calibrate", help="measure whether the verifier's confidence is trustworthy (reliability curve + false-high-confidence)")
    cal_p.add_argument("--config", default=None)
    cal_p.add_argument("--llm", action="store_true",
                       help="also run the suite-independent reference oracle (needs ANTHROPIC_API_KEY)")
    cal_p.add_argument("--gauntlet", action="store_true",
                       help="run the survival-gauntlet calibration proof (plain vs survived vs seeded)")
    cal_p.add_argument("--seed", action="store_true",
                       help="include the seeded-graveyard cohort (leave-one-out)")
    report_p = sub.add_parser(
        "report", help="point-and-go: auto-detect a repo's code + tests and mutation-score its suite (no goal/layout setup)")
    report_p.add_argument("repo")
    report_p.add_argument("--config", default=None)
    report_p.add_argument("--max-mutants", type=int, default=None, dest="max_mutants")
    report_p.add_argument("--source", action="append", default=None,
                          help="override the source path(s) to verify (repeatable; a file or a package dir)")
    report_p.add_argument("--tests", action="append", default=None,
                          help="override the test path(s) (repeatable; a file or a tests dir)")
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

    if args.command == "harden":
        return _cmd_harden(args)

    if args.command == "survive":
        return _cmd_survive(args)

    if args.command == "gauntlet":
        return _cmd_gauntlet(args)

    if args.command == "graveyard":
        return _cmd_graveyard(args)

    if args.command == "population":
        return _cmd_population(args)

    if args.command == "supervise":
        return _cmd_supervise(args)

    if args.command == "adjudicate":
        return _cmd_adjudicate(args)

    if args.command == "check":
        return _cmd_check(args)

    if args.command == "calibrate":
        return _cmd_calibrate(args)

    if args.command == "report":
        return _cmd_report(args)

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
    # The reference oracle is a SUITE-INDEPENDENT, execution-grounded signal: it differential-
    # tests the solution against an independently generated implementation, so it catches
    # green-but-wrong solutions whose bugs live in the test suite's blind spots — exactly the
    # cases mutation/hold-out (both suite-derived) miss. Calibration showed those false-trusts
    # dominate without it, so it runs by default here (opt out via oracle_enabled or --no-llm-verify).
    oracle_client = verify_client if config.oracle_enabled else None
    result = solve(goal_dir, config, examiner, builder, write_tests=write_tests, confirm=confirm,
                   intent_client=verify_client, property_client=verify_client,
                   oracle_client=oracle_client)

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
