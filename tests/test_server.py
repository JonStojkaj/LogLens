import asyncio
import json

import pytest

from loglens import server


def test_tools_are_registered_read_only(served):
    tools = {t.name: t for t in asyncio.run(server.server.list_tools())}
    assert set(tools) == {
        "list_runs",
        "search_logs",
        "error_summary",
        "find_regressions",
        "correlate_errors",
    }
    assert all(t.annotations.read_only_hint for t in tools.values())


def test_call_tool_over_mcp(served):
    result = asyncio.run(server.server.call_tool("list_runs", {}))
    payload = json.loads(result.content[0].text)
    assert [r["run"] for r in payload["runs"]] == ["nightly-1041", "nightly-1042"]


def test_paths_outside_the_log_dir_are_rejected(served):
    with pytest.raises(ValueError, match="inside the log directory"):
        server.list_runs(path="../")
    with pytest.raises(ValueError, match="no logs found"):
        server.list_runs(path="nightly-9999")


def test_search_limit_is_capped(served):
    result = server.search_logs(limit=10_000)
    assert result["returned"] <= server.MAX_LIMIT


def test_time_range_filter(served):
    result = server.search_logs(
        run="nightly-1042", since="2026-11-05T22:00:00Z", until="2026-11-05T22:00:10Z"
    )
    assert result["total_matches"] > 0
    assert all(r["ts"] <= "2026-11-05T22:00:10+00:00" for r in result["records"])


def test_cache_reloads_after_change(served, tmp_path, monkeypatch):
    monkeypatch.setenv("LOGLENS_LOG_DIR", str(tmp_path))
    log = tmp_path / "a.jsonl"
    log.write_text(
        '{"ts": "2026-11-05T10:00:00Z", "service": "a", "level": "ERROR", "message": "x"}\n'
    )
    assert server.list_runs()["runs"][0]["lines"] == 1
    log.write_text(
        log.read_text()
        + '{"ts": "2026-11-05T10:00:01Z", "service": "a", "level": "ERROR", "message": "y"}\n'
    )
    assert server.list_runs()["runs"][0]["lines"] == 2
