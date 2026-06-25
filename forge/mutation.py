# forge/mutation.py
from __future__ import annotations

import ast
from dataclasses import dataclass


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
