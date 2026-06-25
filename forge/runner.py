from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from forge.scoring import FailureInfo, TestResult, parse_report


class Runner:
    def __init__(self, solution_dir: Path, frozen_tests: Path, test_command: list[str]) -> None:
        self.solution_dir = Path(solution_dir)
        self.frozen_tests = Path(frozen_tests)
        self.test_command = list(test_command)

    def run(self) -> TestResult:
        self._restore_frozen_tests()
        fd, report_str = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        report_path = Path(report_str)
        cmd = self.test_command + ["--json-report", "--json-report-file", str(report_path)]
        try:
            proc = subprocess.run(
                cmd, cwd=self.solution_dir, capture_output=True, text=True
            )
            if not report_path.exists() or report_path.stat().st_size == 0:
                return TestResult(
                    passed=0, failed=0, errors=1, total=1,
                    failures=[FailureInfo("collection", proc.stderr or proc.stdout or "no report")],
                )
            try:
                report = json.loads(report_path.read_text())
            except json.JSONDecodeError:
                return TestResult(
                    passed=0, failed=0, errors=1, total=1,
                    failures=[FailureInfo("collection", proc.stderr or proc.stdout or "malformed report")],
                )
            return parse_report(report)
        finally:
            report_path.unlink(missing_ok=True)

    def _restore_frozen_tests(self) -> None:
        dest = self.solution_dir / "tests"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(self.frozen_tests, dest)
