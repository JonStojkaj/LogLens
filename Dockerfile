FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir . && loglens-synth /data/logs

ENV LOGLENS_LOG_DIR=/data/logs
# MCP over stdio: run with `docker run -i` and mount your own logs at /data/logs.
ENTRYPOINT ["loglens-server"]
