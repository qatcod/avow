from hermit.checks import run_checks, combine_checks, CheckResult
from hermit.scoring import TestResult


def test_run_checks_pass_and_fail(tmp_path):
    checks = [
        {"name": "ok", "command": ["python", "-c", "import sys; sys.exit(0)"]},
        {"name": "bad", "command": ["python", "-c", "import sys; sys.stderr.write('boom'); sys.exit(1)"]},
    ]
    results = run_checks(tmp_path, checks)
    assert [(c.name, c.passed) for c in results] == [("ok", True), ("bad", False)]
    assert "boom" in results[1].detail


def test_run_checks_missing_command_is_failed_not_crash(tmp_path):
    results = run_checks(tmp_path, [{"name": "nope", "command": ["this_tool_does_not_exist_xyz123"]}])
    assert results[0].passed is False


def test_run_checks_non_executable_command_is_failed_not_crash(tmp_path):
    # a file that exists but isn't executable -> PermissionError -> failed check, not a crash
    script = tmp_path / "notexec.sh"
    script.write_text("echo hi\n")  # written without the +x bit
    results = run_checks(tmp_path, [{"name": "x", "command": [str(script)]}])
    assert results[0].passed is False


def test_run_checks_empty_command_is_misconfigured(tmp_path):
    results = run_checks(tmp_path, [{"name": "empty", "command": []}])
    assert results[0].passed is False and "misconfigured" in results[0].detail


def test_run_checks_missing_command_key_is_misconfigured(tmp_path):
    results = run_checks(tmp_path, [{"name": "nocmd"}])  # no `command` key at all
    assert results[0].passed is False and "misconfigured" in results[0].detail


def test_combine_checks_folds_into_result():
    base = TestResult(passed=2, failed=0, errors=0, total=2, failures=[])
    combined = combine_checks(base, [CheckResult("a", True, ""), CheckResult("b", False, "bad")])
    assert combined.passed == 3 and combined.failed == 1 and combined.total == 4
    assert combined.is_green is False
    assert any("check::b" in f.nodeid for f in combined.failures)


def test_combine_checks_empty_returns_unchanged():
    base = TestResult(passed=1, failed=0, errors=0, total=1, failures=[])
    assert combine_checks(base, []) is base


# --- Feature A: metric-threshold checks -----------------------------------

def test_metric_check_under_max_passes(tmp_path):
    r = run_checks(tmp_path, [{"name": "size", "command": ["python", "-c", "print(400)"], "max": 500}])
    assert r[0].passed is True


def test_metric_check_over_max_fails(tmp_path):
    r = run_checks(tmp_path, [{"name": "size", "command": ["python", "-c", "print(640)"], "max": 500}])
    assert r[0].passed is False and "> max 500" in r[0].detail


def test_metric_check_under_min_fails(tmp_path):
    r = run_checks(tmp_path, [{"name": "cov", "command": ["python", "-c", "print(85)"], "min": 90}])
    assert r[0].passed is False and "< min 90" in r[0].detail


def test_metric_check_both_bounds(tmp_path):
    ok = run_checks(tmp_path, [{"name": "b", "command": ["python", "-c", "print(50)"], "min": 10, "max": 100}])
    assert ok[0].passed is True
    bad = run_checks(tmp_path, [{"name": "b", "command": ["python", "-c", "print(5)"], "min": 10, "max": 100}])
    assert bad[0].passed is False


def test_metric_check_uses_last_number_by_default(tmp_path):
    # noisy output; the metric is the last numeric token
    r = run_checks(tmp_path, [{"name": "m", "command": ["python", "-c", "print('scanned 3 files; total 420')"], "max": 500}])
    assert r[0].passed is True


def test_metric_check_pattern_with_capture_group(tmp_path):
    r = run_checks(tmp_path, [{"name": "cov",
                               "command": ["python", "-c", "print('coverage: 94.2% of 1000 lines')"],
                               "pattern": r"coverage: ([\d.]+)%", "min": 90}])
    assert r[0].passed is True


def test_metric_check_unparseable_output_fails(tmp_path):
    r = run_checks(tmp_path, [{"name": "m", "command": ["python", "-c", "print('no numbers here')"], "max": 10}])
    assert r[0].passed is False and "could not parse" in r[0].detail


def test_metric_check_missing_command_still_failed(tmp_path):
    r = run_checks(tmp_path, [{"name": "m", "command": ["this_tool_does_not_exist_xyz"], "max": 10}])
    assert r[0].passed is False


def test_exit_code_check_unaffected_by_metric_path(tmp_path):
    # no max/min -> still pure exit-code semantics
    r = run_checks(tmp_path, [{"name": "e", "command": ["python", "-c", "print(999)"]}])
    assert r[0].passed is True  # exits 0 regardless of the number printed
