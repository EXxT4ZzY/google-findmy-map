FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Vendor the upstream library this project builds on, pinned to a specific
# commit. Review this SHA before building and bump it deliberately (it is a
# third-party dependency cloned at build time -- see SECURITY.md).
ARG GFM_UPSTREAM_REF=d46e952
RUN git clone https://github.com/leonboe1/GoogleFindMyTools.git /app/vendor \
    && git -C /app/vendor checkout "${GFM_UPSTREAM_REF}"

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY service/ /app/service
COPY web/ /app/web

# COPY preserves the source files' permissions as-is, whatever they happened
# to be on the host this was built on. The container runs as a non-root user
# (see docker-compose.yml `user:`), so force everything world-readable here
# instead of depending on host umask/ACLs to have gotten it right.
RUN chmod -R a+rX /app/vendor /app/service /app/web

# Writable location for the SQLite database (GFM_HISTORY_DB). Owned by the
# default non-root UID; the compose init step re-chowns the bind-mounted
# host directory to the configured PUID:PGID. GFM_HISTORY_FILE is only used
# to import a pre-SQLite history.json once on startup, if present.
RUN mkdir -p /data && chown 1000:1000 /data
ENV GFM_HISTORY_DB=/data/history.db \
    GFM_HISTORY_FILE=/data/history.json

WORKDIR /app/service
EXPOSE 8080
CMD ["python", "main.py"]
