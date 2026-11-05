import pytest

from loglens import server
from loglens.parser import read_logs
from loglens.synth import generate


@pytest.fixture(scope="session")
def log_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("logs")
    generate(out, seed=7)
    return out


@pytest.fixture(scope="session")
def records(log_dir):
    recs, skipped = read_logs(log_dir)
    assert skipped == 0
    return recs


@pytest.fixture
def served(log_dir, monkeypatch):
    monkeypatch.setenv("LOGLENS_LOG_DIR", str(log_dir))
    server._cache.clear()
    return log_dir
