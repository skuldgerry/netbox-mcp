---
name: netbox-mcp-operator
description: Query, audit, create, update, and delete NetBox infrastructure data through the skuldgerry/netbox-mcp MCP tools. Use when a user asks to inspect inventory, IPAM, circuits, tenancy, virtualization, change history, or global search in NetBox; reconcile desired state; or perform explicit NetBox mutations while resolving object IDs and dependencies safely.
---

# NetBox MCP Operator

Operate NetBox through the connected `netbox_*` MCP tools. Keep reads efficient, make writes deliberate, and verify mutations against the live object.

## Prerequisite

Require a connected instance of `skuldgerry/netbox-mcp` configured with `NETBOX_URL` and `NETBOX_TOKEN`. If the tools are unavailable, stop and explain that the MCP server must be connected. Never request, print, or expose the token.

Read [references/tool-catalog.md](references/tool-catalog.md) when selecting a tool, resolving an object type, or planning a multi-object change.

## Choose the operation

- Use `netbox_search_objects` for broad discovery when the object kind is unclear.
- Use `netbox_get_objects` for a known object type and filters. Always pass `fields` unless the full payload is needed.
- Use `netbox_get_object_by_id` only when the numeric ID is known.
- Use `netbox_get_changelogs` for audit, attribution, and recent-change questions.
- Prefer a specialized create/update/delete tool when one exists.
- Use generic `netbox_create_object`, `netbox_update_object`, or `netbox_delete_object` only for a supported object type without a suitable specialized tool.

## Read workflow

1. Translate the request into one or more NetBox object types and filters.
2. Start with the narrowest query that can answer the request.
3. Request only identifying and decision-relevant fields such as `id`, `name`, `status`, `site`, `tenant`, `description`, or type-specific address fields.
4. Follow relationships with focused queries instead of returning large nested records.
5. State when results are empty, truncated, ambiguous, or dependent on the connected instance's permissions.
6. Summarize the result in the user's terms; include numeric IDs when they are useful for subsequent changes.

## Write workflow

1. Treat a request to create, update, or delete as authorization only for the objects and fields explicitly in scope.
2. Resolve every foreign-key object to a unique numeric ID with a read query. Never guess IDs from names, slugs, VLAN numbers, addresses, or prior environments.
3. Inspect the target immediately before an update or delete. If lookup returns zero or multiple plausible matches, stop and ask for the missing discriminator.
4. Build the smallest payload that implements the requested change. Do not resend unrelated fields.
5. For create, check the natural unique key first, such as slug, name within scope, VLAN ID plus group/site, prefix plus VRF, IP address, device name, or circuit ID plus provider.
6. Before a delete, show the exact type, ID, name, and relevant parent or scope. Ask for confirmation unless the user already explicitly requested deletion of that uniquely identified object in the current request.
7. Invoke one mutation at a time when dependencies or blast radius are unclear. Create parents before children; delete children before parents.
8. Read the affected object or collection after create/update. For delete, query the former ID or unique key and report that absence as verification. If verification is unavailable, say so explicitly.

## Reconciliation and bulk requests

Compute a plan before mutating:

1. Read current objects using stable identifiers and minimal fields.
2. Partition the desired state into create, update, unchanged, ambiguous, and delete sets.
3. Present counts and any ambiguous matches.
4. Do not infer deletions from omission unless the user explicitly asks for authoritative reconciliation or cleanup.
5. Apply changes in dependency order and stop on the first unexpected failure.
6. Re-read the affected scope and report successes and failures separately.

## Guardrails

- Never disable TLS verification or broaden token permissions unless the user explicitly asks and understands the risk.
- Never fabricate object types or endpoint paths. Generic tools accept only types supported by this server.
- Never pass a display value where an integer relationship ID is required.
- Never retry a failed create blindly; first query whether the first attempt succeeded.
- Treat cables, interfaces, IP assignments, prefixes, VLANs, and parent containers as dependency-sensitive.
- Preserve CIDR notation for prefixes and IP addresses.
- Keep secrets out of summaries, logs, payload examples, and error reports.

## Response format

For reads, report the answer, scope/filters, and notable ambiguity. For writes, report the action, object type, ID, changed fields, and verification result. For multi-object work, provide compact created/updated/unchanged/failed counts and list only actionable exceptions.
