# Contributor guidance

Run `uv sync --locked --dev`, `uv run ruff check src tests scripts`,
`uv run ruff format --check src tests scripts`, and `uv run pytest`.
For container changes also run `python scripts/container_smoke.py IMAGE`.
See `docs/maintenance.md` for maintenance, triage, and release boundaries.

## Code Review Rules

- Preserve independent NetBox and MCP authentication. Plugin discovery must remain
  opt-in and generic plugin writes must require an exact type/operation allowlist.
- PR code runs only on ephemeral GitHub-hosted runners without production secrets
  or a path into the home lab. A workflow with write permissions must never check
  out or execute a PR head or consume its artifacts as executable code.
- A passing build or liveness probe is not proof of MCP compatibility or a safe
  release. Preserve authenticated MCP and rejected-auth smoke tests. Missing or
  failed security scans are unknown coverage, never zero findings. Never merge,
  publish an image, or deploy automatically without the maintainer's approval.
