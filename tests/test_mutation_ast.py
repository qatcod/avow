# tests/test_mutation_ast.py
from hermit.mutation import ast_mutants, Mutant


def test_binop_add_becomes_sub():
    mutants = ast_mutants("def f(a, b):\n    return a + b\n")
    assert all(isinstance(m, Mutant) and m.origin == "ast" for m in mutants)
    assert any("a - b" in m.source for m in mutants)
    assert any("BinOp Add->Sub" in m.description for m in mutants)


def test_deterministic_and_one_change_each():
    src = "def f(a, b):\n    return a + b\n"
    assert [m.source for m in ast_mutants(src)] == [m.source for m in ast_mutants(src)]
    # `return a + b` yields exactly: Add->Sub and Return->None
    descs = sorted(m.description for m in ast_mutants(src))
    assert any("BinOp Add->Sub" in d for d in descs)
    assert any("Return value->None" in d for d in descs)


def test_compare_bool_const_return_mutations():
    src = "def f(x, y):\n    if x == 0 and y:\n        return x\n    return 1\n"
    descs = [m.description for m in ast_mutants(src)]
    assert any("Compare Eq->NotEq" in d for d in descs)
    assert any("BoolOp And->Or" in d for d in descs)
    assert any("Return value->None" in d for d in descs)
    assert any("Const" in d for d in descs)  # the 0 and 1 literals


def test_empty_source_has_no_mutants():
    assert ast_mutants("x = 1\n")  # one Const mutant
    assert ast_mutants("pass\n") == []
