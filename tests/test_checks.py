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
