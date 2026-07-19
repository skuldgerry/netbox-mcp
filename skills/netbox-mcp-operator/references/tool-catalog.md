# Tool catalog

## Read tools

| Tool | Use |
| --- | --- |
| `netbox_get_objects` | Filter a known object type; use `fields` to limit output |
| `netbox_get_object_by_id` | Retrieve one object by numeric ID |
| `netbox_get_changelogs` | Query the NetBox object-change audit trail |
| `netbox_search_objects` | Search broadly across supported infrastructure types |

## Generic write tools

Use `netbox_create_object`, `netbox_update_object`, and `netbox_delete_object` only when no specialized tool fits. The generic tools require an exact dotted object type such as `dcim.site` or `ipam.vlan`.

## Specialized write families

The repository exposes create/update/delete families for:

- Sites, tenants, tenant groups, tags, VLANs, and VLAN groups
- Regions and locations
- VRFs, prefixes, IP addresses, and IP ranges
- Devices, interfaces, device types, manufacturers, and racks
- Circuits, providers, and circuit types
- Virtual machines and clusters

It also exposes create-only `netbox_create_rack_role`; create/delete cable tools; and the generic tools for other supported types.

Prefer the specialized family because its signature makes required fields and relationship IDs explicit. Use the tool schema supplied by the MCP client as the authority for exact arguments.

## Common dotted object types

| Domain | Object types |
| --- | --- |
| DCIM | `dcim.site`, `dcim.region`, `dcim.location`, `dcim.rack`, `dcim.device`, `dcim.devicetype`, `dcim.devicerole`, `dcim.manufacturer`, `dcim.interface`, `dcim.cable`, `dcim.platform` |
| IPAM | `ipam.vrf`, `ipam.prefix`, `ipam.ipaddress`, `ipam.iprange`, `ipam.vlan`, `ipam.vlangroup`, `ipam.aggregate`, `ipam.asn`, `ipam.role`, `ipam.service` |
| Tenancy | `tenancy.tenant`, `tenancy.tenantgroup`, `tenancy.contact`, `tenancy.contactgroup`, `tenancy.contactrole` |
| Circuits | `circuits.circuit`, `circuits.provider`, `circuits.circuittype`, `circuits.circuittermination`, `circuits.providernetwork` |
| Virtualization | `virtualization.virtualmachine`, `virtualization.cluster`, `virtualization.clustertype`, `virtualization.vminterface`, `virtualization.virtualdisk` |
| Extras | `extras.tag`, `extras.configcontext`, `extras.customfield`, `extras.journalentry`, `extras.webhook` |
| VPN and wireless | `vpn.tunnel`, `vpn.l2vpn`, `wireless.wirelesslan`, `wireless.wirelesslink` |

The complete supported set lives in `src/netbox_mcp_server/netbox_types.py`. Do not assume plugin-provided NetBox types are supported.

## Efficient field sets

- Device: `id`, `name`, `status`, `device_type`, `role`, `site`, `primary_ip4`
- IP address: `id`, `address`, `status`, `dns_name`, `assigned_object`, `description`
- Prefix: `id`, `prefix`, `status`, `vrf`, `site`, `tenant`, `description`
- Interface: `id`, `name`, `type`, `enabled`, `device`, `description`
- VLAN: `id`, `vid`, `name`, `status`, `group`, `site`, `tenant`
- Site: `id`, `name`, `slug`, `status`, `region`, `tenant`, `description`

Start with these sets and add fields only when the question requires them.

## Dependency order

Typical creation order is tenant/region/site, manufacturer/device type/role, device, interface, then cable or IP assignment. For IPAM, create VRF/VLAN group/site context before prefixes, VLANs, IP addresses, or ranges. Reverse this order for deletions.
