# forge/mutation.py
from __future__ import annotations

import ast
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from forge.runner import Runner


@dataclass
class Mutant:
    source: str
    description: str
    origin: str  # "ast" | "llm"


_BINOP_SWAP = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Div,
               ast.Div: ast.Mult, ast.Mod: ast.Mult}
_CMP_SWAP = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Lt: ast.GtE,
             ast.LtE: ast.Gt, ast.Gt: ast.LtE, ast.GtE: ast.Lt}
_BOOL_SWAP = {ast.And: ast.Or, ast.Or: ast.And}


class _Mutator(ast.NodeTransformer):
    """Applies exactly the `target`-th candidate mutation; with target=-1, only counts."""

    def __init__(self, target: int) -> None:
        self.target = target
        self.counter = 0
        self.description = ""

    def _hit(self, desc: str) -> bool:
        is_target = self.counter == self.target
        if is_target:
            self.description = desc
        self.counter += 1
        return is_target

    def visit_BinOp(self, node):
        self.generic_visit(node)
        t = type(node.op)
        if t in _BINOP_SWAP and self._hit(f"BinOp {t.__name__}->{_BINOP_SWAP[t].__name__}"):
            node.op = _BINOP_SWAP[t]()
        return node

    def visit_Compare(self, node):
        self.generic_visit(node)
        if node.ops:
            t = type(node.ops[0])
            if t in _CMP_SWAP and self._hit(f"Compare {t.__name__}->{_CMP_SWAP[t].__name__}"):
                node.ops[0] = _CMP_SWAP[t]()
        return node

    def visit_BoolOp(self, node):
        self.generic_visit(node)
        t = type(node.op)
        if t in _BOOL_SWAP and self._hit(f"BoolOp {t.__name__}->{_BOOL_SWAP[t].__name__}"):
            node.op = _BOOL_SWAP[t]()
        return node

    def visit_Constant(self, node):
        v = node.value
        if isinstance(v, bool):
            if self._hit(f"Const {v}->{not v}"):
                return ast.copy_location(ast.Constant(not v), node)
        elif isinstance(v, int):
            if self._hit(f"Const {v}->{v + 1}"):
                return ast.copy_location(ast.Constant(v + 1), node)
        elif isinstance(v, str):
            if self._hit("Const str->" + ("empty" if v else "nonempty")):
                return ast.copy_location(ast.Constant("" if v else "forge_mutant"), node)
        return node

    def visit_Return(self, node):
        self.generic_visit(node)
        if node.value is not None and not (
            isinstance(node.value, ast.Constant) and node.value.value is None
        ):
            if self._hit("Return value->None"):
                node.value = ast.copy_location(ast.Constant(None), node)
        return node


def ast_mutants(source: str) -> list[Mutant]:
    counter = _Mutator(-1)
    counter.visit(ast.parse(source))
    out: list[Mutant] = []
    for i in range(counter.counter):
        m = _Mutator(i)
        tree = m.visit(ast.parse(source))
        ast.fix_missing_locations(tree)
        out.append(Mutant(source=ast.unparse(tree), description=m.description, origin="ast"))
    return out


@dataclass
class Survivor:
    file: str
    description: str
    origin: str


@dataclass
class MutationResult:
    total: int
    killed: int
    survived: int
    score: float
    survivors: list[Survivor]
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    baseline_green: bool = True


def run_mutation_testing(
    solution_dir,
    frozen_tests,
    test_command,
    *,
    max_ast_mutants: int = 50,
    llm_n: int = 0,
    timeout: int = 120,
    client=None,
    model=None,
    goal: str = "",
) -> MutationResult:
    solution_dir = Path(solution_dir)

    # Baseline guard: a kill rate is only meaningful if the suite passes on the
    # unmutated solution. Otherwise every mutant "fails" too and the score is a lie.
    baseline = Runner(solution_dir, frozen_tests, test_command, timeout=timeout).run()
    if not baseline.is_green:
        return MutationResult(0, 0, 0, 0.0, [], 0, 0, baseline_green=False)

    modules = sorted(solution_dir.glob("*.py"))
    pool: list[tuple[str, Mutant]] = []
    for mod in modules:
        try:
            src = mod.read_text(encoding="utf-8")
            ms = ast_mutants(src)
        except (SyntaxError, ValueError, UnicodeDecodeError):
            continue  # skip modules we can't parse/decode (the tool runs on any repo)
        for m in ms:
            pool.append((mod.name, m))
    pool = pool[:max_ast_mutants]

    llm_input = llm_output = 0
    if llm_n and client is not None:
        for mod in modules:
            try:
                src = mod.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            ms, i_tok, o_tok = llm_mutants(src, goal, client, model, llm_n)
            llm_input += i_tok
            llm_output += o_tok
            for m in ms:
                pool.append((mod.name, m))

    killed = 0
    survivors: list[Survivor] = []
    for mod_name, mut in pool:
        with tempfile.TemporaryDirectory(prefix="forge-mut-") as tmp:
            sol = Path(tmp) / "sol"
            shutil.copytree(solution_dir, sol)
            (sol / mod_name).write_text(mut.source, encoding="utf-8")
            result = Runner(sol, frozen_tests, test_command, timeout=timeout).run()
        if not result.is_green:
            killed += 1
        else:
            survivors.append(Survivor(file=mod_name, description=mut.description, origin=mut.origin))

    total = len(pool)
    score = 1.0 if total == 0 else killed / total
    return MutationResult(total, killed, total - killed, score, survivors, llm_input, llm_output, baseline_green=True)


class _MutantSpec(BaseModel):
    description: str
    source: str


class _MutantList(BaseModel):
    mutants: list[_MutantSpec]


_LLM_PROMPT = """\
You are a mutation-testing engine. Produce exactly {n} variants of the module below, \
each introducing ONE realistic bug — a plausible mistake a developer might make \
(off-by-one, wrong operator, swapped argument, missed edge case) — NOT a syntax error. \
Each variant must be the COMPLETE module source with the single bug applied. A correct, \
rigorous test suite should FAIL on each variant.

The module implements this goal:
{goal}

MODULE:
{source}
"""


def llm_mutants(source: str, goal: str, client, model: str, n: int) -> tuple[list[Mutant], int, int]:
    if n <= 0 or client is None:
        return [], 0, 0
    response = client.messages.parse(
        model=model,
        max_tokens=8000,
        messages=[{"role": "user", "content": _LLM_PROMPT.format(n=n, goal=goal, source=source)}],
        output_format=_MutantList,
    )
    usage = response.usage
    mutants = [
        Mutant(source=s.source, description=f"LLM: {s.description}", origin="llm")
        for s in response.parsed_output.mutants[:n]
    ]
    return mutants, getattr(usage, "input_tokens", 0), getattr(usage, "output_tokens", 0)
