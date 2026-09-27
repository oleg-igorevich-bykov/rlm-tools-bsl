FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -s /bin/bash rlm

# Pre-create volume mount points with correct ownership.
# Docker initializes named volumes from image content on first mount.
RUN mkdir -p /home/rlm/.config/rlm-tools-bsl/logs /home/rlm/.cache/rlm-tools-bsl \
    && chown -R rlm:rlm /home/rlm/.config /home/rlm/.cache

WORKDIR /home/rlm

# Copy build context for local wheel detection
COPY --chown=rlm:rlm . /tmp/build/

USER rlm

# Install from local wheel if present in dist/, otherwise from PyPI.
# For developers who want to pin a version from source (e.g. custom patches):
#   uv build          # creates dist/*.whl from current sources
#   docker compose up -d --build
#
# Retried: a dropped connection to PyPI mid-resolution can make pip walk the
# whole (unbounded) anthropic/openai version history and report a false
# ResolutionImpossible, even though the pinned ranges resolve cleanly on a
# stable connection. Retrying the whole install clears it.
RUN install_pkg() { \
      if ls /tmp/build/dist/*.whl 1>/dev/null 2>&1; then \
        echo "Installing from local wheel..." && \
        pip install --user --no-cache-dir /tmp/build/dist/*.whl; \
      else \
        echo "Installing from PyPI..." && \
        pip install --user --no-cache-dir rlm-tools-bsl; \
      fi; \
    }; \
    n=0; \
    until install_pkg; do \
      n=$((n + 1)); \
      [ "$n" -ge 3 ] && exit 1; \
      echo "pip install failed, retrying ($n/3)..." >&2; \
      sleep 5; \
    done && rm -rf /tmp/build

ENV PATH="/home/rlm/.local/bin:$PATH"
ENV RLM_TRANSPORT=streamable-http
ENV RLM_HOST=0.0.0.0
ENV RLM_PORT=9000

EXPOSE 9000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:9000/health')"

COPY --chown=rlm:rlm --chmod=755 docker-entrypoint.sh /home/rlm/docker-entrypoint.sh
ENTRYPOINT ["/home/rlm/docker-entrypoint.sh"]
