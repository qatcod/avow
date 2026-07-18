import avow.cli as cli


def test_calibrate_gauntlet_stub_mode_prints_cohorts(capsys):
    rc = cli.main(["calibrate", "--gauntlet", "--seed"])   # no --llm -> deterministic stub mode
    out = capsys.readouterr().out
    assert rc == 0
    assert "plain-green:" in out
    assert "survived (empty graveyard):" in out
    assert "survived (seeded graveyard):" in out
    assert "STUB MODE" in out                                # honest label: mechanism, not real numbers
    assert "not a proof of correctness" in out.lower()       # retained disclaimer


def test_anthropic_helper_sets_max_retries(monkeypatch):
    import anthropic
    captured = {}
    monkeypatch.setattr(anthropic, "Anthropic", lambda **k: captured.update(k) or "CLIENT")
    from avow.cli import _anthropic
    from avow.config import RunConfig
    _anthropic(RunConfig())
    assert captured["max_retries"] == 6
    _anthropic(RunConfig(llm_max_retries=9))
    assert captured["max_retries"] == 9
