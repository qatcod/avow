from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from forge.scoring import FailureInfo, TestResult, parse_report


class Runner:
    def __init__(
        self,
        solution_dir: Path,
        frozen_tests: Path,
        test_command: list[str],
        timeout: int = 120,
    ) -> None:
        self.solution_dir = Path(solution_dir)
        self.frozen_tests = Path(frozen_tests)
        self.test_command = list(test_command)
        self.timeout = timeout

    def run(self) -> TestResult:
        with tempfile.TemporaryDirectory(prefix="forge-grade-") as tmp:
            graded = Path(tmp) / "graded"
            shutil.copytree(self.solution_dir, graded)
            # Anti-cheat: grade ONLY against the frozen suite. Strip any builder-authored
            # tests — a tests/ dir, root-level test files, or a root conftest — so they
            # cannot affect collection or inflate the score.
            tests_dir = graded / "tests"
            if tests_dir.exists():
                shutil.rmtree(tests_dir)
            for stray in (*graded.glob("test_*.py"), *graded.glob("*_test.py"), *graded.glob("conftest.py")):
                stray.unlink()
            shutil.copytree(self.frozen_tests, tests_dir)

            fd, report_str = tempfile.mkstemp(suffix=".json")
            os.close(fd)
            report_path = Path(report_str)
            cmd = self.test_command + ["--json-report", "--json-report-file", str(report_path)]
            try:
                proc = subprocess.run(
                    cmd, cwd=graded, capture_output=True, text=True, timeout=self.timeout
                )
            except subprocess.TimeoutExpired:
                report_path.unlink(missing_ok=True)
                return TestResult(
                    passed=0, failed=0, errors=1, total=1,
                    failures=[FailureInfo("timeout", f"tests exceeded {self.timeout}s")],
                )
            try:
                if not report_path.exists() or report_path.stat().st_size == 0:
                    return TestResult(
                        passed=0, failed=0, errors=1, total=1,
                        failures=[FailureInfo("collection", proc.stderr or proc.stdout or "no report")],
                    )
                try:
                    report = json.loads(report_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    return TestResult(
                        passed=0, failed=0, errors=1, total=1,
                        failures=[FailureInfo("collection", proc.stderr or proc.stdout or "malformed report")],
                    )
                return parse_report(report)
            finally:
                report_path.unlink(missing_ok=True)
