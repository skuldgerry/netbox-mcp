FROM python:3.14-alpine3.23@sha256:e7cff362a12454395f8dc99607c21a602ea880cdce03538877b90c2ba932b16f AS builder

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev

COPY . /app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev


FROM python:3.14-alpine3.23@sha256:e7cff362a12454395f8dc99607c21a602ea880cdce03538877b90c2ba932b16f
LABEL org.opencontainers.image.title="NetBox MCP Server" \
      org.opencontainers.image.description="An MCP server for reading and managing NetBox" \
      org.opencontainers.image.url="https://github.com/skuldgerry/netbox-mcp" \
      org.opencontainers.image.source="https://github.com/skuldgerry/netbox-mcp" \
      org.opencontainers.image.licenses="Apache-2.0"
ENV PYTHONUNBUFFERED=1

RUN apk add --no-cache ca-certificates \
    # Package installation belongs to the builder; remove pip and its bundled
    # bootstrap copy so unused vendored dependencies are not shipped at runtime.
    && python -m pip uninstall --yes pip \
    && rm -rf /usr/local/lib/python3.14/ensurepip \
    && python -c "import importlib.util; assert importlib.util.find_spec('pip') is None; assert importlib.util.find_spec('ensurepip') is None" \
    && addgroup -g 1000 appuser \
    && adduser -D -u 1000 -G appuser appuser

COPY --from=builder --chown=appuser:appuser /app /app

WORKDIR /app

USER appuser

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["netbox-mcp-server"]
