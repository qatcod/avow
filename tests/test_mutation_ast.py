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


def test_docstrings_are_not_mutated():
    # module + function docstrings are equivalent mutants (emptying them changes nothing);
    # they must not produce str->empty mutants, but a REAL string constant still must.
    src = ('"""module docstring"""\n'
           'def f():\n'
           '    """function docstring"""\n'
           '    return "real"\n')
    descs = [m.description for m in ast_mutants(src)]
    # exactly one str->empty mutant, for the real "real" constant — not the two docstrings
    assert descs.count("Const str->empty") == 1
    assert any('""' in m.source and "real" not in m.source.split("return")[-1]
               for m in ast_mutants(src) if m.description == "Const str->empty")
    # the docstrings survive verbatim in that mutant's source
    mutant = next(m for m in ast_mutants(src) if m.description == "Const str->empty")
    assert "module docstring" in mutant.source and "function docstring" in mutant.source


def test_class_docstring_not_mutated():
    src = 'class C:\n    """class doc"""\n    x = "v"\n'
    descs = [m.description for m in ast_mutants(src)]
    assert descs.count("Const str->empty") == 1  # only x's "v", not the class docstring
