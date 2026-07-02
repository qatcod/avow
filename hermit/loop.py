# hermit/loop.py
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from hermit.budget import Budget
from hermit.config import RunConfig
from hermit.examiner import Examiner, TestFile, split_suite
from hermit.memory import AttemptRecord, RunLog
from hermit.backtranslation import run_intent_check
from hermit.panel import panel_intent_check
from hermit.mutation import run_mutation_testing
from hermit.runner import Runner
from hermit.workspace import Workspace
from hermit.confidence import aggregate_confidence
from hermit.properties import generate_property_tests
from hermit.oracle import run_oracle_check, generate_oracle
from hermit.supervisor import review_trajectory
from hermit.adjudicator import adjudicate_failures
from hermit.checks import run_checks, combine_checks


@dataclass
class SolveResult:
    success: bool
    best_score: float
    iterations: int
    reason: str
    best_dir: Path | None
    mutation_score: float | None = None
    survivors: int = 0
    intent_score: float | None = None
    confidence: float | None = None
    confidence_breakdown: dict = field(default_factory=dict)
    oracle_agreement: float | None = None
    suspected_bad_tests: list = field(default_factory=list)


def _write_tests(dest: Path, tests: list[TestFile]) -> None:
    if dest.exists():
        import shutil
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for t in tests:
        (dest / Path(t.path).name).write_text(t.content)


def solve(
    goal_dir: Path,
    config: RunConfig,
    examiner: Examiner,
    builder,
    *,
    now=time.monotonic,
    write_tests: bool = True,
    confirm=None,
    mutation_client=None,
    intent_client=None,
    escalate=None,
    property_client=None,
    oracle_client=None,
    supervisor_client=None,
    adjudicator_client=None,
) -> SolveResult:
    goal_dir = Path(goal_dir)
    goal = (goal_dir / "goal.md").read_text()

    hermit_dir = goal_dir / ".hermit"
    frozen = goal_dir / "tests_frozen"
    holdout = goal_dir / "tests_holdout"
    best_dir = hermit_dir / "best"

    budget = Budget(
        max_cost_usd=config.max_cost_usd,
        max_iterations=config.max_iterations,
        max_wall_seconds=config.max_wall_seconds,
        started_at=now(),
    )

    intent_score = None
    panel_agreement = None

    if write_tests:
        ex = examiner.write_tests(goal)
        budget.charge_tokens(config.examiner_model, ex.input_tokens, ex.output_tokens)
        visible, held = split_suite(ex.suite.tests, config.holdout_fraction)
        if config.property_tests_enabled and property_client is not None:
            props, p_in, p_out = generate_property_tests(
                goal, property_client, config.property_model, config.property_tests_n)
            budget.charge_tokens(config.property_model, p_in, p_out)
            visible = visible + props
        oracle_ref_code = None
        if config.oracle_converge_target and oracle_client is not None:
            pair, o_in, o_out = generate_oracle(goal, oracle_client, config.oracle_model)
            budget.charge_tokens(config.oracle_model, o_in, o_out)
            if pair is not None:
                visible = visible + [TestFile(path="test_oracle_converge.py", content=pair.diff_test_code)]
                oracle_ref_code = pair.reference_code
        _write_tests(frozen, visible)
        _write_tests(holdout, held)
        if oracle_ref_code is not None:
            (frozen / "ref.py").write_text(oracle_ref_code, encoding="utf-8")
        if confirm is not None and not confirm(ex.suite.test_plan):
            return SolveResult(False, 0.0, 0, "aborted", None)
        if config.intent_check_enabled and intent_client is not None:
            before = budget.spent_usd
            if config.panel_enabled and len(config.panel_models) > 1:
                pr = panel_intent_check(goal, frozen, intent_client, config.panel_models)
                for _m, _i, _o in pr.usage:
                    budget.charge_tokens(_m, _i, _o)
                intent_score = pr.score
                panel_agreement = pr.agreement
                RunLog(hermit_dir / "run.jsonl").record(AttemptRecord(
                    iteration=0, score=0.0, is_green=False,
                    diff_summary=f"intent {pr.score:.2f} agreement {pr.agreement:.2f}; {len(pr.divergences)} divergences",
                    failing=pr.divergences, plan="panel intent: " + pr.inferred_goal[:160],
                    cost_usd=budget.spent_usd - before,
                ))
            else:
                ir = run_intent_check(goal, frozen, intent_client, config.backtranslation_model)
                budget.charge_tokens(config.backtranslation_model, ir.input_tokens, ir.output_tokens)
                intent_score = ir.score
                RunLog(hermit_dir / "run.jsonl").record(AttemptRecord(
                    iteration=0, score=0.0, is_green=False,
                    diff_summary=f"intent match {ir.score:.2f}; {len(ir.divergences)} divergences",
                    failing=ir.divergences, plan="intent check: " + ir.inferred_goal[:160],
                    cost_usd=budget.spent_usd - before,
                ))

    log = RunLog(hermit_dir / "run.jsonl")
    workspace = Workspace(hermit_dir / "ws")
    runner = Runner(workspace.solution_dir, frozen, config.test_command, timeout=config.test_timeout_seconds)

    best_score = -1.0
    have_best = False
    rounds_without_improvement = 0
    best_failures: list = []
    reason = "max_iterations"
    attempt_history: list = []
    supervisor_fired = False
    supervisor_hint = None

    while True:
        stopped = budget.exhausted(now())
        if stopped is not None:
            reason = stopped
            break

        budget.tick_iteration()
        workspace.seed_from(best_dir if have_best else None)

        attempt_goal = goal if supervisor_hint is None else f"{goal}\n\nSUPERVISOR GUIDANCE: {supervisor_hint}"
        outcome = builder.attempt(workspace.solution_dir, attempt_goal, best_failures)
        budget.charge_usd(outcome.cost_usd)

        test_result = runner.run()
        result = test_result
        if config.checks:
            result = combine_checks(
                test_result,
                run_checks(workspace.solution_dir, config.checks, config.test_timeout_seconds,
                           strip_config=config.strip_check_config),
            )

        rec = AttemptRecord(
            iteration=budget.iterations,
            score=result.score,
            is_green=result.is_green,
            diff_summary=outcome.plan[:200],
            failing=[f.nodeid for f in result.failures],
            plan=outcome.plan,
            cost_usd=outcome.cost_usd,
        )
        log.record(rec)
        attempt_history.append(rec)

        improved = result.score > best_score
        if improved:
            workspace.promote_to(best_dir)
            best_score = result.score
            have_best = True
            best_failures = result.failures
            rounds_without_improvement = 0
        else:
            rounds_without_improvement += 1

        # Checks fold into the grade, but they must never manufacture a green on a
        # suite that collected zero tests: "no tests = not verified" is the guard
        # that keeps an empty/broken suite from passing on passing checks alone.
        # (With checks == [], result is test_result and this reduces to the old
        # `result.is_green`, since is_green already requires total > 0.)
        if result.is_green and test_result.total > 0:
            holdout_score = _holdout_score(holdout, best_dir, config)
            mscore: float | None = None
            surv = 0
            mut_cost = 0.0
            if config.mutation_enabled:
                before = budget.spent_usd
                mr = run_mutation_testing(
                    best_dir, frozen, config.test_command,
                    max_ast_mutants=config.max_ast_mutants,
                    llm_n=(config.llm_mutants_n if mutation_client is not None else 0),
                    timeout=config.test_timeout_seconds,
                    client=mutation_client, model=config.mutation_model, goal=goal,
                )
                budget.charge_tokens(config.mutation_model, mr.llm_input_tokens, mr.llm_output_tokens)
                mut_cost = budget.spent_usd - before
                mscore, surv = mr.score, mr.survived

            oracle_agreement: float | None = None
            if config.oracle_enabled and oracle_client is not None:
                before = budget.spent_usd
                orc = run_oracle_check(best_dir, goal, oracle_client, config.oracle_model,
                                       config.test_command, config.test_timeout_seconds)
                budget.charge_tokens(config.oracle_model, orc.input_tokens, orc.output_tokens)
                oracle_agreement = orc.agreement
                log.record(AttemptRecord(
                    iteration=budget.iterations, score=result.score, is_green=True,
                    diff_summary=f"oracle agreement {orc.agreement}; {orc.counterexample[:80]}",
                    failing=[], plan="oracle", cost_usd=budget.spent_usd - before,
                ))

            conf = aggregate_confidence(
                {"holdout": holdout_score, "mutation": mscore, "intent": intent_score,
                 "oracle": oracle_agreement},
                config.confidence_weights,
            )
            confidence = conf.score if conf.breakdown else None
            breakdown = conf.breakdown
            log.record(AttemptRecord(
                iteration=budget.iterations, score=result.score, is_green=True,
                diff_summary=f"confidence {confidence}; mutation {mscore}; {breakdown}",
                failing=[], plan="confidence", cost_usd=mut_cost,
            ))

            floor_breached = config.confidence_gating and (
                holdout_score < config.holdout_floor
                or (panel_agreement is not None and panel_agreement < config.panel_agreement_floor)
                or (oracle_agreement is not None and oracle_agreement < config.oracle_floor)
            )
            gated = floor_breached or (
                config.confidence_gating and confidence is not None
                and confidence < config.confidence_threshold)
            if not gated:
                return SolveResult(True, best_score, budget.iterations, "green", best_dir,
                                   mscore, surv, intent_score=intent_score,
                                   confidence=confidence, confidence_breakdown=breakdown,
                                   oracle_agreement=oracle_agreement)
            if escalate is not None and escalate(breakdown):
                return SolveResult(True, best_score, budget.iterations, "green_human_override", best_dir,
                                   mscore, surv, intent_score=intent_score,
                                   confidence=confidence, confidence_breakdown=breakdown,
                                   oracle_agreement=oracle_agreement)
            return SolveResult(False, best_score, budget.iterations, "low_confidence", best_dir,
                               mscore, surv, intent_score=intent_score,
                               confidence=confidence, confidence_breakdown=breakdown,
                               oracle_agreement=oracle_agreement)

        if (config.supervisor_enabled and supervisor_client is not None and not supervisor_fired
                and rounds_without_improvement >= config.supervisor_patience):
            supervisor_fired = True
            before = budget.spent_usd
            verdict, s_in, s_out = review_trajectory(goal, attempt_history, supervisor_client, config.supervisor_model)
            budget.charge_tokens(config.supervisor_model, s_in, s_out)
            if verdict is not None:
                log.record(AttemptRecord(
                    iteration=budget.iterations, score=best_score, is_green=False,
                    diff_summary=f"supervisor: {verdict.recommendation}; {verdict.assessment[:80]}",
                    failing=[], plan="supervisor", cost_usd=budget.spent_usd - before))
                if verdict.escalate or verdict.recommendation == "abort":
                    reason = "supervisor_escalate"
                    break
                if verdict.recommendation == "redirect":
                    supervisor_hint = verdict.assessment

        if rounds_without_improvement >= config.plateau_patience:
            reason = "plateau"
            break
        if budget.iterations >= config.max_iterations:
            reason = "max_iterations"
            break

    suspected_bad_tests = []
    # The adjudicator reasons only about real Examiner-authored tests; drop the
    # `check::<name>` pseudo-nodeids that folded-in verifier checks contribute to
    # best_failures (they aren't collectible pytest tests).
    failing_test_nodeids = [f.nodeid for f in best_failures if not f.nodeid.startswith("check::")]
    if (config.adjudicate_enabled and adjudicator_client is not None
            and have_best and best_score >= config.adjudicate_threshold and failing_test_nodeids):
        before = budget.spent_usd
        adj = adjudicate_failures(
            goal, frozen, failing_test_nodeids, adjudicator_client,
            config.adjudicate_model, config.test_command,
            k=config.adjudicate_references_k, timeout=config.test_timeout_seconds)
        budget.charge_tokens(config.adjudicate_model, adj.input_tokens, adj.output_tokens)
        suspected_bad_tests = [v.test_id for v in adj.verdicts if v.verdict == "test_bug"]
        log.record(AttemptRecord(
            iteration=budget.iterations, score=best_score, is_green=False,
            diff_summary=f"adjudicated {len(adj.verdicts)} failing test(s); suspected bad: {suspected_bad_tests}",
            failing=suspected_bad_tests, plan="adjudicate", cost_usd=budget.spent_usd - before))
    return SolveResult(
        False, max(best_score, 0.0), budget.iterations, reason,
        best_dir if have_best else None, intent_score=intent_score,
        suspected_bad_tests=suspected_bad_tests,
    )


def _holdout_score(holdout: Path, best_dir: Path, config: RunConfig) -> float:
    if not holdout.exists() or not any(holdout.iterdir()):
        return 1.0  # no hold-out configured → no overfit evidence → full signal
    return Runner(best_dir, holdout, config.test_command,
                  timeout=config.test_timeout_seconds).run().score
