import avow.cli as cli


def test_check_cli(tmp_path, capsys):
    cfg = tmp_path / "avow.yaml"
    cfg.write_text(
        'checks:\n'
        '  - name: ok\n'
        '    command: ["python", "-c", "import sys; sys.exit(0)"]\n'
        '  - name: bad\n'
        '    command: ["python", "-c", "import sys; sys.exit(1)"]\n')
    sol = tmp_path / "sol"
    sol.mkdir()
    rc = cli.main(["check", str(sol), "--config", str(cfg)])
    out = capsys.readouterr().out
    assert "ok: PASS" in out
    assert "bad: FAIL" in out
    assert rc == 2   # a check failed


def test_check_cli_no_checks(tmp_path, capsys):
    rc = cli.main(["check", str(tmp_path)])   # no --config -> default RunConfig, checks=[]
    out = capsys.readouterr().out
    assert rc == 0 and "no checks" in out.lower()
