from pathlib import Path
from types import SimpleNamespace
from forge.mutation import run_mutation_testing, _MutantList, _MutantSpec


CMD = ["python", "-m", "pytest", "-q"]


class FakeMessages:
    def __init__(self, payload):
        self._payload = payload

    def parse(self, **kwargs):
        return SimpleNamespace(parsed_output=self._payload,
                               usage=SimpleNamespace(input_tokens=10, output_tokens=20))


class FakeClient:
    def __init__(self, payload):
        self.messages = FakeMessages(payload)


def test_hybrid_adds_llm_mutants_and_reports_tokens(tmp_path: Path):
    sol = tmp_path / "sol"; sol.mkdir()
    (sol / "lib.py").write_text("def add(a, b):\n    return a + b\n")
    frozen = tmp_path / "frozen"; frozen.mkdir()
    (frozen / "test_lib.py").write_text(
        "from lib import add\n"
        "def test_pos(): assert add(2, 3) == 5\n"
        "def test_neg(): assert add(-1, 1) == 0\n"
    )
    payload = _MutantList(mutants=[
        _MutantSpec(description="broke it", source="def add(a, b):\n    return a * b\n"),
    ])
    client = FakeClient(payload)
    ast_only = run_mutation_testing(sol, frozen, CMD)
    hybrid = run_mutation_testing(sol, frozen, CMD, llm_n=1, client=client,
                                  model="claude-sonnet-4-6", goal="build add")
    assert hybrid.total == ast_only.total + 1            # one LLM mutant added
    assert hybrid.llm_input_tokens == 10 and hybrid.llm_output_tokens == 20
    # a*b fails add(2,3)==5 (6!=5), so the LLM mutant is killed → strong suite keeps score 1.0
    assert hybrid.score == 1.0
