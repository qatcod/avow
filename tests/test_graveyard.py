from avow.graveyard import AttackPattern, record, load, recent


def _p(cat, desc):
    return AttackPattern(category=cat, description=desc, origin_goal="g", example_input="x")


def test_record_and_load_roundtrip(tmp_path):
    gy = tmp_path / "gy.jsonl"
    assert record(_p("boundary", "probe numeric boundaries"), gy) is True
    loaded = load(gy)
    assert len(loaded) == 1 and loaded[0].category == "boundary"
    assert loaded[0].description == "probe numeric boundaries"


def test_record_dedups_on_category_and_description(tmp_path):
    gy = tmp_path / "gy.jsonl"
    assert record(_p("boundary", "Probe Numeric Boundaries"), gy) is True
    assert record(_p("boundary", "probe numeric boundaries  "), gy) is False   # same key (case/space-insensitive)
    assert len(load(gy)) == 1


def test_recent_returns_last_n_in_order(tmp_path):
    gy = tmp_path / "gy.jsonl"
    for i in range(5):
        record(_p("c", f"pattern {i}"), gy)
    r = recent(gy, 2)
    assert [p.description for p in r] == ["pattern 3", "pattern 4"]


def test_load_missing_file_is_empty(tmp_path):
    assert load(tmp_path / "nope.jsonl") == []


def test_load_skips_corrupt_lines(tmp_path):
    gy = tmp_path / "gy.jsonl"
    record(_p("c", "good"), gy)
    with gy.open("a") as f:
        f.write("not json\n{}\n")
    assert [p.description for p in load(gy)] == ["good"]   # corrupt/incomplete lines skipped
