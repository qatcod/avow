from pathlib import Path
from avow.graveyard import AttackPattern, record, load, recent, relevant


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


def test_load_skips_schema_drifted_lines(tmp_path):
    # Valid JSON but not a valid AttackPattern (e.g. wrong type / future-required field missing):
    # a ValidationError line must be skipped, not propagated.
    gy = tmp_path / "gy.jsonl"
    record(_p("c", "good"), gy)
    with gy.open("a") as f:
        f.write('{"category": 123, "description": ["not", "a", "string"]}\n')
    assert [p.description for p in load(gy)] == ["good"]


def test_load_unreadable_store_is_best_effort(tmp_path, monkeypatch):
    gy = tmp_path / "gy.jsonl"
    gy.write_text("placeholder")

    def denied(*_args, **_kwargs):
        raise PermissionError("temporarily unreadable")

    monkeypatch.setattr(Path, "read_text", denied)
    assert load(gy) == []
    assert relevant("numeric boundary", gy, 5) == []


def test_relevant_ranks_matching_pattern_above_unrelated(tmp_path):
    gy = tmp_path / "gy.jsonl"
    record(AttackPattern(category="recursion-depth", description="probe deep recursion on factorial"), gy)
    record(AttackPattern(category="unicode-edge", description="probe emoji surrogate pairs"), gy)
    out = relevant("compute factorial with deep recursion for an integer", gy, 5)
    assert [p.category for p in out] == ["recursion-depth"]   # only the overlapping pattern, unrelated excluded


def test_relevant_category_outweighs_description(tmp_path):
    gy = tmp_path / "gy.jsonl"
    # cat_match: goal token "boundary" hits the CATEGORY (weight 3)
    record(AttackPattern(category="boundary-check", description="unrelated words here"), gy)
    # desc_match: goal token "boundary" hits only the DESCRIPTION (weight 1)
    record(AttackPattern(category="unrelated-slug", description="probe a boundary somewhere"), gy)
    out = relevant("test the boundary", gy, 5)
    assert [p.category for p in out] == ["boundary-check", "unrelated-slug"]   # 3 > 1


def test_relevant_strict_excludes_zero_score_and_novel_goal_is_empty(tmp_path):
    gy = tmp_path / "gy.jsonl"
    record(AttackPattern(category="numeric-boundary", description="probe numeric boundaries"), gy)
    assert relevant("wholly unrelated xyzzy plover topic", gy, 5) == []   # no overlap -> empty (strict)


def test_relevant_recency_breaks_score_ties(tmp_path):
    gy = tmp_path / "gy.jsonl"
    older = AttackPattern(category="alpha-one", description="boundary check alpha")
    newer = AttackPattern(category="beta-two", description="boundary check beta")
    record(older, gy)
    record(newer, gy)   # more recent
    out = relevant("probe boundary conditions", gy, 5)
    # equal score (both match only 'boundary' in description) -> most-recent first
    assert [p.category for p in out] == ["beta-two", "alpha-one"]


def test_relevant_n_le_zero_and_missing_store_are_empty(tmp_path):
    gy = tmp_path / "gy.jsonl"
    record(AttackPattern(category="numeric-boundary", description="probe numeric boundaries"), gy)
    assert relevant("numeric boundary", gy, 0) == []
    assert relevant("numeric boundary", tmp_path / "nope.jsonl", 5) == []


def test_relevant_does_not_score_example_input(tmp_path):
    gy = tmp_path / "gy.jsonl"
    # category + description share nothing with the goal; the only overlap ('plover') is in
    # example_input, which is NOT scored -> the pattern is excluded
    record(AttackPattern(category="zulu-quebec", description="oscar tango words", example_input="plover"), gy)
    assert relevant("the plover flew", gy, 5) == []


def test_relevant_caps_result_at_n(tmp_path):
    gy = tmp_path / "gy.jsonl"
    for i in range(5):
        record(AttackPattern(category=f"boundary-{i}", description="numeric boundary case"), gy)
    out = relevant("numeric boundary", gy, 2)   # all 5 match equally -> only the top-n come back
    assert len(out) == 2
    assert [p.category for p in out] == ["boundary-4", "boundary-3"]   # most-recent-first tiebreak


def test_default_graveyard_path_layout():
    from avow.graveyard import default_graveyard_path
    p = default_graveyard_path()
    assert p == Path.home() / ".avow" / "graveyard.jsonl"


def test_record_returns_true_on_new_false_on_duplicate(tmp_path):
    gy = tmp_path / "gy.jsonl"
    assert record(_p("numeric-boundary", "probe boundaries"), gy) is True
    assert record(_p("numeric-boundary", "probe boundaries"), gy) is False   # duplicate key


def test_recent_n_equals_one_returns_last(tmp_path):
    gy = tmp_path / "gy.jsonl"
    record(_p("a-one", "first"), gy)
    record(_p("b-two", "second"), gy)
    assert [p.category for p in recent(gy, 1)] == ["b-two"]


def test_attack_pattern_optional_fields_default_empty():
    p = AttackPattern(category="c", description="d")
    assert p.origin_goal == "" and p.example_input == ""


def test_record_creates_missing_parent_dirs(tmp_path):
    gy = tmp_path / "nested" / "sub" / "gy.jsonl"   # parent dirs do NOT exist yet
    assert record(_p("c", "d"), gy) is True         # record must create the tree (parents=True)
    assert [p.description for p in load(gy)] == ["d"]
