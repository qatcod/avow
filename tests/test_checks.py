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


# --- Feature B: strip_check_config anti-cheat ------------------------------

_SEES_RUFF = ["python", "-c", "import os,sys; sys.exit(0 if os.path.exists('ruff.toml') else 1)"]


def test_strip_config_off_sees_builder_config(tmp_path):
    (tmp_path / "ruff.toml").write_text("# builder-added config\n")
    r = run_checks(tmp_path, [{"name": "lint", "command": _SEES_RUFF}])  # strip off (default)
    assert r[0].passed is True   # the config file is visible -> exit 0


def test_strip_config_on_removes_builder_config(tmp_path):
    (tmp_path / "ruff.toml").write_text("# builder-added config\n")
    r = run_checks(tmp_path, [{"name": "lint", "command": _SEES_RUFF}], strip_config=True)
    assert r[0].passed is False  # config stripped in the sandbox -> exit 1


def test_strip_config_preserves_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n")
    sees = ["python", "-c", "import os,sys; sys.exit(0 if os.path.exists('pyproject.toml') else 1)"]
    r = run_checks(tmp_path, [{"name": "x", "command": sees}], strip_config=True)
    assert r[0].passed is True   # pyproject deliberately NOT stripped


def test_strip_config_on_still_sees_solution_code(tmp_path):
    # the solution code itself is copied into the sandbox, so checks that read it still work
    (tmp_path / "lib.py").write_text("VALUE = 7\n")
    reads = ["python", "-c", "import sys; sys.exit(0 if 'VALUE = 7' in open('lib.py').read() else 1)"]
    r = run_checks(tmp_path, [{"name": "x", "command": reads}], strip_config=True)
    assert r[0].passed is True


def test_strip_config_removes_nested_config(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "ruff.toml").write_text("# nested builder config\n")
    sees = ["python", "-c", "import os,sys; sys.exit(0 if os.path.exists('src/ruff.toml') else 1)"]
    r = run_checks(tmp_path, [{"name": "x", "command": sees}], strip_config=True)
    assert r[0].passed is False   # nested config is stripped too


def test_strip_config_survives_broken_symlink(tmp_path):
    (tmp_path / "dangling").symlink_to(tmp_path / "does_not_exist")
    r = run_checks(tmp_path, [{"name": "x", "command": ["python", "-c", "import sys; sys.exit(0)"]}],
                   strip_config=True)
    assert r[0].passed is True    # a broken symlink must not crash the sandbox build


# --- review hardening: metric edge cases ----------------------------------

def test_metric_string_bound_is_coerced(tmp_path):
    r = run_checks(tmp_path, [{"name": "m", "command": ["python", "-c", "print(640)"], "max": "500"}])
    assert r[0].passed is False and "max 500" in r[0].detail   # "500" coerced, 640 > 500


def test_metric_nonnumeric_bound_is_misconfig_not_crash(tmp_path):
    r = run_checks(tmp_path, [{"name": "m", "command": ["python", "-c", "print(5)"], "max": "abc"}])
    assert r[0].passed is False and "misconfigured" in r[0].detail


def test_metric_pattern_optional_group_no_crash(tmp_path):
    r = run_checks(tmp_path, [{"name": "m", "command": ["python", "-c", "print('foo')"],
                               "pattern": r"(\d+)?foo", "max": 10}])
    assert r[0].passed is False and "could not parse" in r[0].detail


def test_metric_nonzero_exit_fails_even_with_number_in_output(tmp_path):
    # a crashing command must not pass on a number in its traceback/stderr
    cmd = ["python", "-c", "import sys; sys.stderr.write('boom 42'); sys.exit(1)"]
    r = run_checks(tmp_path, [{"name": "m", "command": cmd, "max": 100}])
    assert r[0].passed is False and "exited 1" in r[0].detail


def test_metric_stdout_only_ignores_stderr_number(tmp_path):
    cmd = ["python", "-c", "import sys; sys.stderr.write('999999\\n'); print(10)"]
    r = run_checks(tmp_path, [{"name": "m", "command": cmd, "max": 100}])
    assert r[0].passed is True   # parses stdout's 10, not stderr's 999999


def test_metric_parses_thousands_separators(tmp_path):
    cmd = ["python", "-c", "print('total 1,234,567 bytes')"]
    r = run_checks(tmp_path, [{"name": "m", "command": cmd, "max": 500000}])
    assert r[0].passed is False and "1234567" in r[0].detail   # 1.23M > 500k, not 567


def test_metric_scientific_notation(tmp_path):
    r = run_checks(tmp_path, [{"name": "m", "command": ["python", "-c", "print('size 1e6')"], "max": 500000}])
    assert r[0].passed is False   # 1e6 == 1,000,000 > 500,000 (not 6)


def test_metric_hyphenated_token_not_misread_as_negative(tmp_path):
    # "utf-8" must not parse as -8 (which would trip any min or pass any max)
    r = run_checks(tmp_path, [{"name": "m", "command": ["python", "-c", "print('encoding: utf-8')"], "min": 0}])
    assert r[0].passed is False and "could not parse" in r[0].detail


def test_metric_detail_no_scientific_notation(tmp_path):
    r = run_checks(tmp_path, [{"name": "m", "command": ["python", "-c", "print(12345678)"], "max": 100}])
    assert "12345678" in r[0].detail and "e+" not in r[0].detail


def test_metric_present_but_null_bound_is_misconfig(tmp_path):
    r = run_checks(tmp_path, [{"name": "m", "command": ["python", "-c", "print(5)"], "max": None}])
    assert r[0].passed is False and "misconfigured" in r[0].detail
