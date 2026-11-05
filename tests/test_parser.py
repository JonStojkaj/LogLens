from datetime import UTC, datetime

from loglens.parser import level_rank, parse_line, read_logs


def test_parses_a_valid_line():
    r = parse_line(
        '{"ts": "2026-11-05T10:00:00Z", "service": "driver", "level": "warn",'
        ' "run": "r1", "message": "hello", "gpu": "RTX 4090"}'
    )
    assert r is not None
    assert r.ts == datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
    assert r.level == "WARNING"
    assert r.fields == {"gpu": "RTX 4090"}


def test_missing_zone_is_treated_as_utc():
    r = parse_line('{"ts": "2026-11-05T10:00:00", "service": "s", "level": "INFO", "message": "m"}')
    assert r is not None and r.ts.tzinfo is not None
    assert r.run == "unknown"


def test_rejects_malformed_lines():
    assert parse_line("not json") is None
    assert parse_line('{"service": "s", "level": "INFO", "message": "no ts"}') is None
    assert (
        parse_line(
            '{"ts": "2026-11-05T10:00:00Z", "service": "s", "level": "LOUD", "message": "m"}'
        )
        is None
    )
    assert parse_line('["a list"]') is None
    assert parse_line("   ") is None


def test_read_logs_skips_bad_lines_and_sorts(tmp_path):
    (tmp_path / "a.jsonl").write_text(
        '{"ts": "2026-11-05T10:00:05Z", "service": "a", "level": "INFO", "message": "late"}\n'
        "garbage\n"
        "\n"
        '{"ts": "2026-11-05T10:00:01Z", "service": "a", "level": "INFO", "message": "early"}\n'
    )
    records, skipped = read_logs(tmp_path)
    assert [r.message for r in records] == ["early", "late"]
    assert skipped == 1


def test_level_order():
    assert level_rank("DEBUG") < level_rank("INFO") < level_rank("WARNING") < level_rank("ERROR")
    assert level_rank("fatal") == level_rank("CRITICAL")
