import pytest

from loglens import analysis


def test_signature_removes_variable_parts():
    assert analysis.signature("TDR timeout after 2031 ms on GPU 0") == (
        "TDR timeout after <n> ms on GPU <n>"
    )
    assert analysis.signature("pipeline 0x1f2e3d4c failed") == "pipeline <hex> failed"
    assert analysis.signature("retry for 'textures/a.pak'") == "retry for <str>"
    assert analysis.signature("job 123e4567-e89b-12d3-a456-426614174000 done") == "job <id> done"
    # Digits inside words are part of the name, not a value.
    assert analysis.signature("RTX4090 ok") == "RTX4090 ok"


def test_list_runs(records):
    runs = {r["run"]: r for r in analysis.list_runs(records)}
    assert set(runs) == {"nightly-1041", "nightly-1042"}
    assert runs["nightly-1042"]["errors"] > runs["nightly-1041"]["errors"]


def test_search_filters_and_limits(records):
    result = analysis.search(
        records, run="nightly-1042", service="driver", min_level="ERROR", limit=2
    )
    assert result["total_matches"] == 13
    assert result["returned"] == 2
    assert all(r["service"] == "driver" for r in result["records"])


def test_error_summary_groups_by_signature(records):
    summary = analysis.error_summary(records, run="nightly-1042")
    top = summary["groups"][0]
    assert top["signature"] == "Device removed: TDR timeout after <n> ms on GPU <n>"
    assert top["count"] == 13
    assert sum(g["count"] for g in summary["groups"]) == summary["total"]


def test_find_regressions_reports_new_and_resolved(records):
    result = analysis.find_regressions(
        records, baseline_run="nightly-1041", candidate_run="nightly-1042"
    )
    new = {e["signature"] for e in result["new"]}
    assert "Device removed: TDR timeout after <n> ms on GPU <n>" in new
    assert "Shader compilation took <n> ms for pipeline <hex>" in new
    resolved = {e["signature"] for e in result["resolved"]}
    assert resolved == {"Fan curve fallback on GPU <n>"}


def test_find_regressions_rejects_unknown_run(records):
    with pytest.raises(ValueError, match="no log lines"):
        analysis.find_regressions(records, baseline_run="nightly-1041", candidate_run="missing")


def test_correlate_separates_cause_from_consequence(records):
    result = analysis.correlate(records, anchor="TDR timeout", run="nightly-1042")
    assert result["occurrences"] == 13
    related = {e["signature"]: e for e in result["related"]}
    shader = related["Shader compilation took <n> ms for pipeline <hex>"]
    assert shader["share"] == 1.0 and shader["before_share"] == 1.0
    aborted = [e for sig, e in related.items() if "aborted: device lost" in sig]
    assert aborted and all(e["before_share"] == 0.0 for e in aborted)


def test_correlate_without_matches(records):
    assert analysis.correlate(records, anchor="no such error")["occurrences"] == 0
