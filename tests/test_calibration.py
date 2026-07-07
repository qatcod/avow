from hermit.calibration import CalibrationGoal, CalibrationRow, CalibrationReport, run_calibration
from hermit.config import RunConfig


def _oracle_add(m):
    return all(m.add(a, b) == a + b for a in range(-3, 4) for b in range(-3, 4))


def test_calibration_labels_green_but_wrong_offline():
    goal = CalibrationGoal(
        name="add", goal_text="add(a, b) returns a + b",
        tests={"test_a.py": "from lib import add\ndef test_a():\n    assert add(1, 1) == 2\n"},
        variants={
            "correct": "def add(a, b):\n    return a + b\n",
            "green_wrong": "def add(a, b):\n    return 2\n",   # passes the weak test, but wrong
        },
        oracle=_oracle_add,
    )
    report = run_calibration([goal], RunConfig(), oracle_client=None)
    by = {r.variant: r for r in report.rows}
    assert by["correct"].green and by["correct"].correct
    assert by["green_wrong"].green and not by["green_wrong"].correct   # green but WRONG
    assert by["green_wrong"].confidence is not None                    # offline confidence still computed
    assert by["green_wrong"].oracle_agreement is None                 # no oracle client -> no oracle signal


def test_false_high_confidence_metric_and_oracle_floor():
    rows = [
        CalibrationRow("g", "correct", green=True, confidence=0.9, oracle_agreement=1.0, correct=True),
        CalibrationRow("g", "wrong", green=True, confidence=0.9, oracle_agreement=0.0, correct=False),
        CalibrationRow("g", "caught", green=False, confidence=None, oracle_agreement=None, correct=False),
    ]
    rep = CalibrationReport(rows, threshold=0.7)
    assert rep.false_high_confidence(use_oracle=False) == (1, 2)   # 1 false-high of 2 trusted
    assert rep.false_high_confidence(use_oracle=True) == (0, 1)    # oracle floor drops the wrong one


def test_reliability_buckets_bin_by_confidence():
    rows = [
        CalibrationRow("g", "a", True, 0.95, None, True),
        CalibrationRow("g", "b", True, 0.90, None, False),
        CalibrationRow("g", "c", True, 0.60, None, True),
    ]
    rep = CalibrationReport(rows, threshold=0.7)
    buckets = dict(rep.reliability(use_oracle=False))
    # the [0.85,1.01) bucket holds a + b -> 1 of 2 correct
    assert buckets[(0.85, 1.01)] == (1, 2)


def test_calibrate_cli_prints_report(monkeypatch, capsys):
    import hermit.calibration as calmod
    import hermit.cli as cli
    rep = CalibrationReport([
        CalibrationRow("g", "correct", True, 0.9, None, True),
        CalibrationRow("g", "wrong", True, 0.9, None, False),
    ], threshold=0.7)
    monkeypatch.setattr(calmod, "run_calibration", lambda goals, config, oracle_client=None: rep)
    assert cli.main(["calibrate"]) == 0
    out = capsys.readouterr().out
    assert "reliability" in out
    assert "1/2 trusted solutions are actually WRONG" in out
