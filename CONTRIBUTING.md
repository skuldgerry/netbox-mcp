# Contributing

Thanks for helping maintain NetBox MCP Enhanced.

## Development setup

1. Install Python 3.11 through 3.14 and [uv](https://docs.astral.sh/uv/).
2. Run `uv sync --locked --dev`.
3. Create a branch from `main`.
4. Make focused changes and add tests.
5. Run `uv run ruff check src tests`, `uv run ruff format --check src tests`, and
   `uv run pytest`.

Do not commit `.env` files, NetBox tokens, MCP bearer tokens, or captured production responses.

## Tool changes

Changes to mutation tools must preserve registration with FastMCP and include tests for the REST
endpoint, HTTP method, and payload shape. Generic tool and object-type catalog changes should stay
in sync. Avoid changing tool names or parameters without documenting the compatibility impact.

## Pull requests

Explain the problem, the chosen approach, and how the change was verified. Link related issues.
Keep generated dependency-lock changes in the same pull request as their dependency declaration.
