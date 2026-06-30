from pathlib import Path
from hermit.memory import RunLog, AttemptRecord


def test_records_round_trip(tmp_path: Path):
    log = RunLog(tmp_path / "nested" / "run.jsonl")
    log.record(AttemptRecord(
        iteration=1, score=0.5, is_green=False,
        diff_summary="added foo.py", failing=["t::b"], plan="try X", cost_usd=0.02,
    ))
    log.record(AttemptRecord(
        iteration=2, score=1.0, is_green=True,
        diff_summary="fixed foo.py", failing=[], plan="fix X", cost_usd=0.03,
    ))
    rows = log.records()
    assert len(rows) == 2
    assert rows[0]["iteration"] == 1 and rows[0]["is_green"] is False
    assert rows[1]["score"] == 1.0 and rows[1]["failing"] == []
