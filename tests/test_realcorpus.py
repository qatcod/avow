import importlib.util
from pathlib import Path

from avow.realcorpus import build_real_corpus
from avow.calibration import CalibrationReport
from avow.config import RunConfig

# a function with a branch the suite never exercises (x > 100), so mutants there survive
_SRC = "def f(x):\n    if x > 100:\n        return 0\n    return x * 2\n"
_TEST = "from lib import f\ndef test_f():\n    assert f(2) == 4 and f(5) == 10\n"  # only x < 100


def _load_f(d):
    spec = importlib.util.spec_from_file_location("m" + str(abs(hash(str(d)))), Path(d) / "lib.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.f


def _agrees(orig_dir, var_dir):
    fo, fv = _load_f(orig_dir), _load_f(var_dir)
    return all(fo(x) == fv(x) for x in range(0, 300))   # fuzz across BOTH branches


def test_real_corpus_extracts_green_but_wrong_from_surviving_mutants(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "lib.py").write_text(_SRC)
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_f.py").write_text(_TEST)

    rows = build_real_corpus(src, tests, [Path("lib.py")], _agrees, RunConfig(), max_cases=5)
    by = {r.variant: r for r in rows}
    # the original is a correct, green case with a computed confidence
    assert by["original"].correct is True and by["original"].green
    assert by["original"].confidence is not None
    # at least one genuinely-wrong surviving mutant was extracted, all green
    wrong = [r for r in rows if not r.correct]
    assert wrong, "should extract at least one green-but-wrong surviving mutant from real code"
    assert all(r.green and r.correct is False for r in wrong)
    # the existing reliability machinery consumes these rows
    rep = CalibrationReport(rows, threshold=0.7)
    fh, total = rep.false_high_confidence(use_oracle=False)
    assert isinstance(fh, int) and isinstance(total, int)
