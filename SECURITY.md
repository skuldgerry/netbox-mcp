# Security Policy

## Supported versions

Security fixes are applied to the latest released version and the active development branch.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting feature for this repository. Do not open a
public issue containing credentials, exploit details, or information that could expose a NetBox
deployment. If private reporting is unavailable, open a minimal issue asking the maintainer for a
private contact channel without including sensitive details.

Never include real `NETBOX_TOKEN` or `MCP_AUTH_TOKEN` values in reports, logs, screenshots, or test
fixtures.

## Deployment boundary

`NETBOX_TOKEN` authorizes this server to call NetBox. `MCP_AUTH_TOKEN` independently authorizes MCP
clients to call this server over HTTP. Use least-privilege NetBox permissions, set a strong MCP
bearer token for network deployments, and terminate TLS before traffic leaves a trusted host.

Plugin discovery is disabled by default. When enabled, discovered plugin types are read-only unless
an exact object type and operation are listed in `PLUGIN_WRITE_RULES`. Keep this allowlist narrow;
NetBox token permissions remain the authoritative control for every request.
