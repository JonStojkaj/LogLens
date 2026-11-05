# LogLens

[![CI](https://github.com/JonStojkaj/LogLens/actions/workflows/ci.yml/badge.svg)](https://github.com/JonStojkaj/LogLens/actions/workflows/ci.yml)

**An MCP server that lets AI agents troubleshoot from service logs:** search them,
group errors, compare a test run against a known-good baseline, and see which
problems of other services show up around an error.

Performance labs run the same benchmarks every night across game builds,
drivers and GPUs. When a run breaks, someone has to read the logs of the test
runner, the driver, the game build and the telemetry side by side. LogLens gives
an agent the tools to do that first pass, while keeping it honest: **every
number comes from code, never from the language model.** The agent can only
explain findings that the tools computed.

## Tools

| Tool | What it answers |
|------|-----------------|
| `list_runs` | Which runs are there, with how many lines, warnings and errors? |
| `search_logs` | Lines filtered by run, service, minimum level, text and time range |
| `error_summary` | The most frequent problems in a run, grouped by message signature |
| `find_regressions` | What is new, more frequent or gone in a candidate run compared with a baseline? |
| `correlate_errors` | Which problems of other services appear around a given error, and do they come before or after it? |

All tools are marked read-only and idempotent, and only read `.jsonl` files
below `LOGLENS_LOG_DIR`; paths that leave that directory are rejected.

## Example

The repository ships a generator for synthetic performance-lab logs
(`loglens-synth`): two nightly runs on four benchmark scenes and three GPUs.
Run `nightly-1042` uses a newer driver, and in two scenes something goes wrong.
These are the real tool results on that data.

`find_regressions(baseline_run="nightly-1041", candidate_run="nightly-1042")`:

| Finding | Signature | Count |
|---------|-----------|------:|
| new | `Shader compilation took <n> ms for pipeline <hex>` | 13 |
| new | `Device removed: TDR timeout after <n> ms on GPU <n>` | 13 |
| new | `Benchmark CityNight aborted: device lost` | 8 |
| new | `Benchmark IndoorArena aborted: device lost` | 5 |
| resolved | `Fan curve fallback on GPU <n>` | 10 in baseline |

`correlate_errors(anchor="TDR timeout", run="nightly-1042")`, 13 occurrences:

| Service | Signature | share | before_share |
|---------|-----------|------:|-------------:|
| game-build | `Shader compilation took <n> ms for pipeline <hex>` | 1.00 | 1.00 |
| test-runner | `Benchmark CityNight aborted: device lost` | 0.62 | 0.00 |
| test-runner | `Benchmark IndoorArena aborted: device lost` | 0.38 | 0.00 |
| game-build | `Asset download retry <n> for <str>` | 0.15 | 1.00 |

Read: every GPU timeout was preceded by a slow shader compilation
(`before_share` 1.0, a candidate cause), and the aborted benchmarks always come
afterwards (a consequence). The asset retries show up near 15 % of the
timeouts only, so they are probably unrelated.

## How it works

- **Signatures.** Variable parts of a message (numbers, hex addresses, ids,
  quoted strings) are replaced by placeholders, so `timeout after 2031 ms` and
  `timeout after 1987 ms` count as the same problem. Digits inside a word stay
  (`RTX4090`).
- **Fair comparisons.** `find_regressions` normalizes counts per 1,000 log
  lines of each run, so a longer run does not look worse just because it logged
  more. A problem counts as *increased* when its rate grows by `ratio` (default
  2×) and it occurs at least `min_count` times.
- **Cause or consequence.** `correlate_errors` looks at a time window around
  every occurrence of the anchor. `share` is the fraction of occurrences a
  problem appears near; `before_share` how often it came first. Correlation is
  not causation: the tool points to candidates, the engineer decides.
- **Robust input.** Logs are JSON Lines (`ts`, `service`, `level`, `message`,
  optional `run` and any extra fields). Malformed lines are counted and skipped,
  not fatal. Timestamps without a zone are read as UTC.
- **Caching.** Parsed logs are kept in memory and re-read only when a file's
  size or modification time changes.

## Quick start

Requires Python 3.11 or newer.

```sh
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
loglens-synth logs                  # write the synthetic sample logs
LOGLENS_LOG_DIR=logs loglens-server # MCP server on stdio
```

Most MCP clients accept a server entry like this:

```json
{
  "mcpServers": {
    "loglens": {
      "command": "/path/to/LogLens/.venv/bin/loglens-server",
      "env": { "LOGLENS_LOG_DIR": "/path/to/your/logs" }
    }
  }
}
```

### Docker

```sh
docker build -t loglens .
docker run -i --rm -v "$PWD/logs:/data/logs" loglens
```

The image contains the sample logs, so it also works without a mount.

## Tests

```sh
pytest -q
ruff check . && ruff format --check .
```

20 tests cover parsing and malformed input, signatures, every analysis function
on the synthetic data with known expected findings, the path restriction, the
cache, and an end-to-end round trip in which an MCP client starts the server as
a subprocess and calls a tool over stdio. GitHub Actions runs them on Python
3.11 to 3.13 and builds the Docker image.

## Limitations and next steps

- Input is JSON Lines only; plain-text formats would need a parser per format.
- Everything is held in memory, which suits nightly runs, not weeks of production logs.
- Grouping is by exact signature. Embedding-based grouping would also merge
  differently worded messages about the same problem.
- Next: link findings to known issues and historical runs, and ingest
  OpenTelemetry logs directly.

## License

MIT
