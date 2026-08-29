# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
uses semantic versioning.

## [Unreleased]

## [1.1.0] - 2026-08-29

### Added

- Optional shared bearer-token authentication for the Streamable HTTP MCP endpoint, ported from
  the official NetBox MCP implementation.
- Configurable HTTP CORS origins and an unauthenticated `/health` liveness route.
- Opt-in discovery of installed NetBox plugin models with REST endpoints, ported from the official
  NetBox MCP implementation. Discovered types are read-only by default.
- Exact, operation-specific `PLUGIN_WRITE_RULES` for enabling generic plugin creates, updates, or
  deletes without broad wildcard access.
- Tests covering HTTP authorization, configuration masking, NetBox token schemes, CRUD routing,
  plugin discovery controls, and write-tool registration.

### Changed

- Upgraded to FastMCP 3.4.7 and expanded supported Python versions to 3.11 through 3.14.
- Migrated the NetBox REST client from `requests` to `httpx`.
- NetBox v2 tokens beginning with `nbt_` now use the `Bearer` authentication scheme; legacy tokens
  continue using `Token`.
- Added NetBox-version fallback for object-type endpoints and current core object-type mappings.
- Docker builds now use the locked dependency graph and exclude local secrets from build context.

### Security

- The Docker Compose template now enables MCP bearer authentication. Existing clients adopting the
  updated template must send `Authorization: Bearer <token>`; replace the placeholder token before
  deployment.

### Fixed

- Corrected the invalid Docker Compose health-check definition.
- Corrected bulk CRUD requests to use NetBox collection endpoints instead of a nonexistent
  `/bulk/` suffix.

[Unreleased]: https://github.com/skuldgerry/netbox-mcp/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/skuldgerry/netbox-mcp/compare/v1.0.0...v1.1.0
