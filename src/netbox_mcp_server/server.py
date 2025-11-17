import argparse
import logging
import sys
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from netbox_mcp_server.config import Settings, configure_logging
from netbox_mcp_server.netbox_client import NetBoxRestClient
from netbox_mcp_server.netbox_types import NETBOX_OBJECT_TYPES


def parse_cli_args() -> dict[str, Any]:
    """
    Parse command-line arguments for configuration overrides.

    Returns:
        dict of configuration overrides (only includes explicitly set values)
    """
    parser = argparse.ArgumentParser(
        description="NetBox MCP Server - Model Context Protocol server for NetBox",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Core NetBox settings
    parser.add_argument(
        "--netbox-url",
        type=str,
        help="Base URL of the NetBox instance (e.g., https://netbox.example.com/)",
    )
    parser.add_argument(
        "--netbox-token",
        type=str,
        help="API token for NetBox authentication",
    )

    # Transport settings
    parser.add_argument(
        "--transport",
        type=str,
        choices=["stdio", "http"],
        help="MCP transport protocol (default: stdio)",
    )
    parser.add_argument(
        "--host",
        type=str,
        help="Host address for HTTP server (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="Port for HTTP server (default: 8000)",
    )

    # Security settings
    ssl_group = parser.add_mutually_exclusive_group()
    ssl_group.add_argument(
        "--verify-ssl",
        action="store_true",
        dest="verify_ssl",
        default=None,
        help="Verify SSL certificates (default)",
    )
    ssl_group.add_argument(
        "--no-verify-ssl",
        action="store_false",
        dest="verify_ssl",
        help="Disable SSL certificate verification (not recommended)",
    )

    # Observability settings
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging verbosity level (default: INFO)",
    )

    args: argparse.Namespace = parser.parse_args()

    overlay: dict[str, Any] = {}
    if args.netbox_url is not None:
        overlay["netbox_url"] = args.netbox_url
    if args.netbox_token is not None:
        overlay["netbox_token"] = args.netbox_token
    if args.transport is not None:
        overlay["transport"] = args.transport
    if args.host is not None:
        overlay["host"] = args.host
    if args.port is not None:
        overlay["port"] = args.port
    if args.verify_ssl is not None:
        overlay["verify_ssl"] = args.verify_ssl
    if args.log_level is not None:
        overlay["log_level"] = args.log_level

    return overlay


# Default object types for global search
DEFAULT_SEARCH_TYPES = [
    "dcim.device",  # Most common search target
    "dcim.site",  # Site names frequently searched
    "ipam.ipaddress",  # IP searches very common
    "dcim.interface",  # Interface names/descriptions
    "dcim.rack",  # Rack identifiers
    "ipam.vlan",  # VLAN names/IDs
    "circuits.circuit",  # Circuit identifiers
    "virtualization.virtualmachine",  # VM names
]

mcp = FastMCP("NetBox")
netbox = None


def validate_filters(filters: dict) -> None:
    """
    Validate that filters don't use multi-hop relationship traversal.

    NetBox API does not support nested relationship queries like:
    - device__site_id (filtering by related object's field)
    - interface__device__site (multiple relationship hops)

    Valid patterns:
    - Direct field filters: site_id, name, status
    - Lookup expressions: name__ic, status__in, id__gt

    Args:
        filters: Dictionary of filter parameters

    Raises:
        ValueError: If filter uses invalid multi-hop relationship traversal
    """
    VALID_SUFFIXES = {
        "n",
        "ic",
        "nic",
        "isw",
        "nisw",
        "iew",
        "niew",
        "ie",
        "nie",
        "empty",
        "regex",
        "iregex",
        "lt",
        "lte",
        "gt",
        "gte",
        "in",
    }

    for filter_name in filters:
        # Skip special parameters
        if filter_name in ("limit", "offset", "fields", "q"):
            continue

        if "__" not in filter_name:
            continue

        parts = filter_name.split("__")

        # Allow field__suffix pattern (e.g., name__ic, id__gt)
        if len(parts) == 2 and parts[-1] in VALID_SUFFIXES:
            continue
        # Block multi-hop patterns and invalid suffixes
        if len(parts) >= 2:
            raise ValueError(
                f"Invalid filter '{filter_name}': Multi-hop relationship "
                f"traversal or invalid lookup suffix not supported. Use direct field filters like "
                f"'site_id' or two-step queries."
            )


@mcp.tool(
    description="""
    Get objects from NetBox based on their type and filters

    Args:
        object_type: String representing the NetBox object type (e.g. "dcim.device", "ipam.ipaddress")
        filters: dict of filters to apply to the API call based on the NetBox API filtering options

                FILTER RULES:
                Valid: Direct fields like {'site_id': 1, 'name': 'router', 'status': 'active'}
                Valid: Lookups like {'name__ic': 'switch', 'id__in': [1,2,3], 'vid__gte': 100}
                Invalid: Multi-hop like {'device__site_id': 1} - NOT supported

                Lookup suffixes: n, ic, nic, isw, nisw, iew, niew, ie, nie,
                                 empty, regex, iregex, lt, lte, gt, gte, in

                Two-step pattern for cross-relationship queries:
                  sites = netbox_get_objects('dcim.site', {'name': 'NYC'})
                  netbox_get_objects('dcim.device', {'site_id': sites[0]['id']})

        fields: Optional list of specific fields to return
                **IMPORTANT: ALWAYS USE THIS PARAMETER TO MINIMIZE TOKEN USAGE**
                Field filtering significantly reduces response payload and is critical for performance.

                - None or [] = returns all fields (NOT RECOMMENDED - use only when you need complete objects)
                - ['id', 'name'] = returns only specified fields (RECOMMENDED)

                Examples:
                - For counting: ['id'] (minimal payload)
                - For listings: ['id', 'name', 'status']
                - For IP addresses: ['address', 'dns_name', 'description']

                Uses NetBox's native field filtering via ?fields= parameter.
                **Always specify only the fields you actually need.**

        brief: returns only a minimal representation of each object in the response.
               This is useful when you need only a list of available objects without any related data.

        limit: Maximum results to return (default 5, max 100)
               Start with default, increase only if needed

        offset: Skip this many results for pagination (default 0)
                Example: offset=0 (page 1), offset=5 (page 2), offset=10 (page 3)

        ordering: Fields used to determine sort order of results.
                  Field names may be prefixed with '-' to invert the sort order.
                  Multiple fields may be specified with a list of strings.

                  Examples:
                  - 'name' (alphabetical by name)
                  - '-id' (ordered by ID descending)
                  - ['facility', '-name'] (by facility, then by name descending)
                  - None, '' or [] (default NetBox ordering)


    Returns:
        Paginated response dict with the following structure:
            - count: Total number of objects matching the query
                     ALWAYS REFER TO THIS FIELD FOR THE TOTAL NUMBER OF OBJECTS MATCHING THE QUERY
            - next: URL to next page (or null if no more pages)
                    ALWAYS REFER TO THIS FIELD FOR THE NEXT PAGE OF RESULTS
            - previous: URL to previous page (or null if on first page)
                        ALWAYS REFER TO THIS FIELD FOR THE PREVIOUS PAGE OF RESULTS
            - results: Array of objects for this page
                       ALWAYS REFER TO THIS FIELD FOR THE OBJECTS ON THIS PAGE

    ENSURE YOU ARE AWARE THE RESULTS ARE PAGINATED BEFORE PROVIDING RESPONSE TO THE USER.

    Valid object_type values:

    """ +
    "\n".join(f"- {t}" for t in sorted(NETBOX_OBJECT_TYPES.keys())) +
    """

    See NetBox API documentation for filtering options for each object type.
    """
)
def netbox_get_objects(
    object_type: str,
    filters: dict,
    fields: list[str] | None = None,
    brief: bool = False,
    limit: Annotated[int, Field(default=5, ge=1, le=100)] = 5,
    offset: Annotated[int, Field(default=0, ge=0)] = 0,
    ordering: str | list[str] | None = None,
):
    """
    Get objects from NetBox based on their type and filters
    """
    # Validate object_type exists in mapping
    if object_type not in NETBOX_OBJECT_TYPES:
        valid_types = "\n".join(f"- {t}" for t in sorted(NETBOX_OBJECT_TYPES.keys()))
        raise ValueError(f"Invalid object_type. Must be one of:\n{valid_types}")

    # Validate filter patterns
    validate_filters(filters)

    # Get API endpoint from mapping
    endpoint = _endpoint_for_type(object_type)

    # Build params with pagination (parameters override filters dict)
    params = filters.copy()
    params["limit"] = limit
    params["offset"] = offset

    if fields:
        params["fields"] = ",".join(fields)

    if brief:
        params["brief"] = "1"

    if ordering:
        if isinstance(ordering, list):
            ordering = ",".join(ordering)
        if ordering.strip() != "":
            params["ordering"] = ordering

    # Make API call
    return netbox.get(endpoint, params=params)


@mcp.tool
def netbox_get_object_by_id(
    object_type: str,
    object_id: int,
    fields: list[str] | None = None,
    brief: bool = False,
):
    """
    Get detailed information about a specific NetBox object by its ID.

    Args:
        object_type: String representing the NetBox object type (e.g. "dcim.device", "ipam.ipaddress")
        object_id: The numeric ID of the object
        fields: Optional list of specific fields to return
                **IMPORTANT: ALWAYS USE THIS PARAMETER TO MINIMIZE TOKEN USAGE**
                Field filtering reduces response payload by 80-90% and is critical for performance.

                - None or [] = returns all fields (NOT RECOMMENDED - use only when you need complete objects)
                - ['id', 'name'] = returns only specified fields (RECOMMENDED)

                Examples:
                - For basic info: ['id', 'name', 'status']
                - For devices: ['id', 'name', 'status', 'site']
                - For IP addresses: ['address', 'dns_name', 'vrf', 'status']

                Uses NetBox's native field filtering via ?fields= parameter.
                **Always specify only the fields you actually need.**
        brief: returns only a minimal representation of the object in the response.
               This is useful when you need only a summary of the object without any related data.

    Returns:
        Object dict (complete or with only requested fields based on fields parameter)
    """
    # Validate object_type exists in mapping
    if object_type not in NETBOX_OBJECT_TYPES:
        valid_types = "\n".join(f"- {t}" for t in sorted(NETBOX_OBJECT_TYPES.keys()))
        raise ValueError(f"Invalid object_type. Must be one of:\n{valid_types}")

    # Get API endpoint from mapping
    endpoint = f"{_endpoint_for_type(object_type)}/{object_id}"

    params = {}
    if fields:
        params["fields"] = ",".join(fields)

    if brief:
        params["brief"] = "1"

    return netbox.get(endpoint, params=params)


@mcp.tool
def netbox_get_changelogs(filters: dict):
    """
    Get object change records (changelogs) from NetBox based on filters.

    Args:
        filters: dict of filters to apply to the API call based on the NetBox API filtering options

    Returns:
        Paginated response dict with the following structure:
            - count: Total number of changelog entries matching the query
                     ALWAYS REFER TO THIS FIELD FOR THE TOTAL NUMBER OF CHANGELOG ENTRIES MATCHING THE QUERY
            - next: URL to next page (or null if no more pages)
                    ALWAYS REFER TO THIS FIELD FOR THE NEXT PAGE OF RESULTS
            - previous: URL to previous page (or null if on first page)
                        ALWAYS REFER TO THIS FIELD FOR THE PREVIOUS PAGE OF RESULTS
            - results: Array of changelog entries for this page
                       ALWAYS REFER TO THIS FIELD FOR THE CHANGELOG ENTRIES ON THIS PAGE

    Filtering options include:
    - user_id: Filter by user ID who made the change
    - user: Filter by username who made the change
    - changed_object_type_id: Filter by numeric ContentType ID (e.g., 21 for dcim.device)
                              Note: This expects a numeric ID, not an object type string
    - changed_object_id: Filter by ID of the changed object
    - object_repr: Filter by object representation (usually contains object name)
    - action: Filter by action type (created, updated, deleted)
    - time_before: Filter for changes made before a given time (ISO 8601 format)
    - time_after: Filter for changes made after a given time (ISO 8601 format)
    - q: Search term to filter by object representation

    Examples:
    To find all changes made to a specific object by ID:
    {"changed_object_id": 123}

    To find changes by object name pattern:
    {"object_repr": "router-01"}

    To find all deletions in the last 24 hours:
    {"action": "delete", "time_after": "2023-01-01T00:00:00Z"}

    Each changelog entry contains:
    - id: The unique identifier of the changelog entry
    - user: The user who made the change
    - user_name: The username of the user who made the change
    - request_id: The unique identifier of the request that made the change
    - action: The type of action performed (created, updated, deleted)
    - changed_object_type: The type of object that was changed
    - changed_object_id: The ID of the object that was changed
    - object_repr: String representation of the changed object
    - object_data: The object's data after the change (null for deletions)
    - object_data_v2: Enhanced data representation
    - prechange_data: The object's data before the change (null for creations)
    - postchange_data: The object's data after the change (null for deletions)
    - time: The timestamp when the change was made
    """
    endpoint = "core/object-changes"

    # Make API call
    return netbox.get(endpoint, params=filters)


@mcp.tool(
    description="""
    Perform global search across NetBox infrastructure.

    Searches names, descriptions, IP addresses, serial numbers, asset tags,
    and other key fields across multiple object types.

    Args:
        query: Search term (device names, IPs, serial numbers, hostnames, site names)
               Examples: 'switch01', '192.168.1.1', 'NYC-DC1', 'SN123456'
        object_types: Limit search to specific types (optional)
                     Default: [""" + "', '".join(DEFAULT_SEARCH_TYPES) + """]
                     Examples: ['dcim.device', 'ipam.ipaddress', 'dcim.site']
        fields: Optional list of specific fields to return (reduces response size) IT IS STRONGLY RECOMMENDED TO USE THIS PARAMETER TO MINIMIZE TOKEN USAGE.
                - None or [] = returns all fields (no filtering)
                - ['id', 'name'] = returns only specified fields
                Examples: ['id', 'name', 'status'], ['address', 'dns_name']
                Uses NetBox's native field filtering via ?fields= parameter
        limit: Max results per object type (default 5, max 100)

    Returns:
        Dictionary with object_type keys and list of matching objects.
        All searched types present in result (empty list if no matches).

    Example:
        # Search for anything matching "switch"
        results = netbox_search_objects('switch')
        # Returns: {
        #   'dcim.device': [{'id': 1, 'name': 'switch-01', ...}],
        #   'dcim.site': [],
        #   ...
        # }

        # Search for IP address
        results = netbox_search_objects('192.168.1.100')
        # Returns: {
        #   'ipam.ipaddress': [{'id': 42, 'address': '192.168.1.100/24', ...}],
        #   ...
        # }

        # Limit search to specific types with field projection
        results = netbox_search_objects(
            'NYC',
            object_types=['dcim.site', 'dcim.location'],
            fields=['id', 'name', 'status']
        )
    """
)
def netbox_search_objects(
    query: str,
    object_types: list[str] | None = None,
    fields: list[str] | None = None,
    limit: Annotated[int, Field(default=5, ge=1, le=100)] = 5,
) -> dict[str, list[dict]]:
    """
    Perform global search across NetBox infrastructure.
    """
    if object_types is None:
        search_types = DEFAULT_SEARCH_TYPES
    else:
        search_types = object_types

    # Validate all object types exist in mapping
    for obj_type in search_types:
        if obj_type not in NETBOX_OBJECT_TYPES:
            valid_types = "\n".join(
                f"- {t}" for t in sorted(NETBOX_OBJECT_TYPES.keys())
            )
            raise ValueError(
                f"Invalid object_type '{obj_type}'. Must be one of:\n{valid_types}"
            )

    results = {obj_type: [] for obj_type in search_types}

    # Build results dictionary (error-resilient)
    for obj_type in search_types:
        try:
            response = netbox.get(
                _endpoint_for_type(obj_type),
                params={
                    "q": query,
                    "limit": limit,
                    "fields": ",".join(fields) if fields else None,
                },
            )
            # Extract results array from paginated response
            results[obj_type] = response.get("results", [])
        except Exception:
            # Continue searching other types if one fails
            # results[obj_type] already has empty list
            continue

    return results


# ============================================================================
# Write Operations - Create, Update, Delete Tools
# ============================================================================

@mcp.tool
def netbox_create_object(
    object_type: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Create a new object in NetBox.

    Args:
        object_type: String representing the NetBox object type (e.g., "dcim.site", "ipam.vlan")
        data: Dictionary containing the object data to create. Required fields vary by object type.
              See NetBox API documentation for required fields.

    Returns:
        The created object as a dict

    Examples:
        # Create a site
        netbox_create_object("dcim.site", {
            "name": "New York DC",
            "slug": "nyc-dc",
            "status": "active"
        })

        # Create a VLAN
        netbox_create_object("ipam.vlan", {
            "name": "VLAN-100",
            "vid": 100,
            "status": "active"
        })
    """
    if object_type not in NETBOX_OBJECT_TYPES:
        valid_types = "\n".join(f"- {t}" for t in sorted(NETBOX_OBJECT_TYPES.keys()))
        raise ValueError(f"Invalid object_type. Must be one of:\n{valid_types}")

    endpoint = _endpoint_for_type(object_type)
    return netbox.create(endpoint, data)


@mcp.tool
def netbox_update_object(
    object_type: str,
    object_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Update an existing object in NetBox.

    Args:
        object_type: String representing the NetBox object type (e.g., "dcim.site", "ipam.vlan")
        object_id: The numeric ID of the object to update
        data: Dictionary containing the fields to update (only include fields you want to change)

    Returns:
        The updated object as a dict

    Examples:
        # Update a site's status
        netbox_update_object("dcim.site", 1, {"status": "planned"})

        # Update a VLAN's name
        netbox_update_object("ipam.vlan", 5, {"name": "VLAN-200"})
    """
    if object_type not in NETBOX_OBJECT_TYPES:
        valid_types = "\n".join(f"- {t}" for t in sorted(NETBOX_OBJECT_TYPES.keys()))
        raise ValueError(f"Invalid object_type. Must be one of:\n{valid_types}")

    endpoint = _endpoint_for_type(object_type)
    return netbox.update(endpoint, object_id, data)


@mcp.tool
def netbox_delete_object(
    object_type: str,
    object_id: int,
) -> bool:
    """
    Delete an object from NetBox.

    Args:
        object_type: String representing the NetBox object type (e.g., "dcim.site", "ipam.vlan")
        object_id: The numeric ID of the object to delete

    Returns:
        True if deletion was successful

    Examples:
        # Delete a site
        netbox_delete_object("dcim.site", 1)

        # Delete a VLAN
        netbox_delete_object("ipam.vlan", 5)
    """
    if object_type not in NETBOX_OBJECT_TYPES:
        valid_types = "\n".join(f"- {t}" for t in sorted(NETBOX_OBJECT_TYPES.keys()))
        raise ValueError(f"Invalid object_type. Must be one of:\n{valid_types}")

    endpoint = _endpoint_for_type(object_type)
    return netbox.delete(endpoint, object_id)


# ============================================================================
# Priority Objects - Sites, Tenants, Tags, VLANs
# ============================================================================

@mcp.tool
def netbox_create_site(
    name: str,
    slug: str,
    status: str = "active",
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Create a new site in NetBox.

    Args:
        name: Site name (required)
        slug: URL-friendly identifier (required)
        status: Site status - "active", "planned", "staging", "decommissioning", "retired" (default: "active")
        data: Additional optional fields as a dictionary (region, tenant, facility, etc.)
              See NetBox API documentation for all available fields

    Returns:
        The created site object as a dict
    """
    payload = {"name": name, "slug": slug, "status": status}
    if data:
        payload.update(data)
    return netbox.create("dcim/sites", payload)


@mcp.tool
def netbox_update_site(
    site_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Update an existing site in NetBox.

    Args:
        site_id: The numeric ID of the site to update
        data: Fields to update as a dictionary (name, slug, status, region, tenant, etc.)

    Returns:
        The updated site object as a dict
    """
    return netbox.update("dcim/sites", site_id, data)


@mcp.tool
def netbox_delete_site(site_id: int) -> bool:
    """
    Delete a site from NetBox.

    Args:
        site_id: The numeric ID of the site to delete

    Returns:
        True if deletion was successful
    """
    return netbox.delete("dcim/sites", site_id)


@mcp.tool
def netbox_create_tenant(
    name: str,
    slug: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Create a new tenant in NetBox.

    Args:
        name: Tenant name (required)
        slug: URL-friendly identifier (required)
        data: Additional optional fields as a dictionary (group, description, comments, etc.)

    Returns:
        The created tenant object as a dict
    """
    payload = {"name": name, "slug": slug}
    if data:
        payload.update(data)
    return netbox.create("tenancy/tenants", payload)


@mcp.tool
def netbox_update_tenant(
    tenant_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Update an existing tenant in NetBox.

    Args:
        tenant_id: The numeric ID of the tenant to update
        data: Fields to update as a dictionary (name, slug, group, description, etc.)

    Returns:
        The updated tenant object as a dict
    """
    return netbox.update("tenancy/tenants", tenant_id, data)


@mcp.tool
def netbox_delete_tenant(tenant_id: int) -> bool:
    """
    Delete a tenant from NetBox.

    Args:
        tenant_id: The numeric ID of the tenant to delete

    Returns:
        True if deletion was successful
    """
    return netbox.delete("tenancy/tenants", tenant_id)


@mcp.tool
def netbox_create_tenant_group(
    name: str,
    slug: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Create a new tenant group in NetBox.

    Args:
        name: Tenant group name (required)
        slug: URL-friendly identifier (required)
        data: Additional optional fields as a dictionary (parent, description, etc.)

    Returns:
        The created tenant group object as a dict
    """
    payload = {"name": name, "slug": slug}
    if data:
        payload.update(data)
    return netbox.create("tenancy/tenant-groups", payload)


@mcp.tool
def netbox_update_tenant_group(
    tenant_group_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Update an existing tenant group in NetBox.

    Args:
        tenant_group_id: The numeric ID of the tenant group to update
        data: Fields to update as a dictionary (name, slug, parent, description, etc.)

    Returns:
        The updated tenant group object as a dict
    """
    return netbox.update("tenancy/tenant-groups", tenant_group_id, data)


@mcp.tool
def netbox_delete_tenant_group(tenant_group_id: int) -> bool:
    """
    Delete a tenant group from NetBox.

    Args:
        tenant_group_id: The numeric ID of the tenant group to delete

    Returns:
        True if deletion was successful
    """
    return netbox.delete("tenancy/tenant-groups", tenant_group_id)


@mcp.tool
def netbox_create_tag(
    name: str,
    slug: str | None = None,
    color: str | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Create a new tag in NetBox.

    Args:
        name: Tag name (required)
        slug: URL-friendly identifier (optional, auto-generated from name if not provided)
        color: Hex color code (optional, e.g., "ff0000")
        data: Additional optional fields as a dictionary (description, etc.)

    Returns:
        The created tag object as a dict
    """
    payload = {"name": name}
    if slug:
        payload["slug"] = slug
    if color:
        payload["color"] = color
    if data:
        payload.update(data)
    return netbox.create("extras/tags", payload)


@mcp.tool
def netbox_update_tag(
    tag_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Update an existing tag in NetBox.

    Args:
        tag_id: The numeric ID of the tag to update
        data: Fields to update as a dictionary (name, slug, color, description, etc.)

    Returns:
        The updated tag object as a dict
    """
    return netbox.update("extras/tags", tag_id, data)


@mcp.tool
def netbox_delete_tag(tag_id: int) -> bool:
    """
    Delete a tag from NetBox.

    Args:
        tag_id: The numeric ID of the tag to delete

    Returns:
        True if deletion was successful
    """
    return netbox.delete("extras/tags", tag_id)


@mcp.tool
def netbox_create_vlan(
    name: str,
    vid: int,
    status: str = "active",
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Create a new VLAN in NetBox.

    Args:
        name: VLAN name (required)
        vid: VLAN ID (1-4094) (required)
        status: VLAN status - "active", "reserved", "deprecated" (default: "active")
        data: Additional optional fields as a dictionary (site, group, tenant, role, description, etc.)

    Returns:
        The created VLAN object as a dict
    """
    payload = {"name": name, "vid": vid, "status": status}
    if data:
        payload.update(data)
    return netbox.create("ipam/vlans", payload)


@mcp.tool
def netbox_update_vlan(
    vlan_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Update an existing VLAN in NetBox.

    Args:
        vlan_id: The numeric ID of the VLAN to update
        data: Fields to update as a dictionary (name, vid, status, site, group, tenant, etc.)

    Returns:
        The updated VLAN object as a dict
    """
    return netbox.update("ipam/vlans", vlan_id, data)


@mcp.tool
def netbox_delete_vlan(vlan_id: int) -> bool:
    """
    Delete a VLAN from NetBox.

    Args:
        vlan_id: The numeric ID of the VLAN to delete

    Returns:
        True if deletion was successful
    """
    return netbox.delete("ipam/vlans", vlan_id)


@mcp.tool
def netbox_create_vlan_group(
    name: str,
    slug: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Create a new VLAN group in NetBox.

    Args:
        name: VLAN group name (required)
        slug: URL-friendly identifier (required)
        data: Additional optional fields as a dictionary (scope_type, scope_id, description, etc.)

    Returns:
        The created VLAN group object as a dict
    """
    payload = {"name": name, "slug": slug}
    if data:
        payload.update(data)
    return netbox.create("ipam/vlan-groups", payload)


@mcp.tool
def netbox_update_vlan_group(
    vlan_group_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Update an existing VLAN group in NetBox.

    Args:
        vlan_group_id: The numeric ID of the VLAN group to update
        data: Fields to update as a dictionary (name, slug, scope_type, scope_id, etc.)

    Returns:
        The updated VLAN group object as a dict
    """
    return netbox.update("ipam/vlan-groups", vlan_group_id, data)


@mcp.tool
def netbox_delete_vlan_group(vlan_group_id: int) -> bool:
    """
    Delete a VLAN group from NetBox.

    Args:
        vlan_group_id: The numeric ID of the VLAN group to delete

    Returns:
        True if deletion was successful
    """
    return netbox.delete("ipam/vlan-groups", vlan_group_id)


# ============================================================================
# Additional Core Infrastructure Objects
# ============================================================================

@mcp.tool
def netbox_create_region(
    name: str,
    slug: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Create a new region in NetBox.

    Args:
        name: Region name (required)
        slug: URL-friendly identifier (required)
        data: Additional optional fields as a dictionary (parent, description, etc.)

    Returns:
        The created region object as a dict
    """
    payload = {"name": name, "slug": slug}
    if data:
        payload.update(data)
    return netbox.create("dcim/regions", payload)


@mcp.tool
def netbox_update_region(
    region_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Update an existing region in NetBox.

    Args:
        region_id: The numeric ID of the region to update
        data: Fields to update as a dictionary (name, slug, parent, description, etc.)

    Returns:
        The updated region object as a dict
    """
    return netbox.update("dcim/regions", region_id, data)


@mcp.tool
def netbox_delete_region(region_id: int) -> bool:
    """
    Delete a region from NetBox.

    Args:
        region_id: The numeric ID of the region to delete

    Returns:
        True if deletion was successful
    """
    return netbox.delete("dcim/regions", region_id)


@mcp.tool
def netbox_create_location(
    name: str,
    site: int,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Create a new location in NetBox.

    Args:
        name: Location name (required)
        site: Site ID (required)
        data: Additional optional fields as a dictionary (parent, status, tenant, description, etc.)

    Returns:
        The created location object as a dict
    """
    payload = {"name": name, "site": site}
    if data:
        payload.update(data)
    return netbox.create("dcim/locations", payload)


@mcp.tool
def netbox_update_location(
    location_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Update an existing location in NetBox.

    Args:
        location_id: The numeric ID of the location to update
        data: Fields to update as a dictionary (name, site, parent, status, etc.)

    Returns:
        The updated location object as a dict
    """
    return netbox.update("dcim/locations", location_id, data)


@mcp.tool
def netbox_delete_location(location_id: int) -> bool:
    """
    Delete a location from NetBox.

    Args:
        location_id: The numeric ID of the location to delete

    Returns:
        True if deletion was successful
    """
    return netbox.delete("dcim/locations", location_id)


# ============================================================================
# IPAM Objects
# ============================================================================

@mcp.tool
def netbox_create_vrf(
    name: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Create a new VRF in NetBox.

    Args:
        name: VRF name (required)
        data: Additional optional fields as a dictionary (rd, tenant, description, etc.)

    Returns:
        The created VRF object as a dict
    """
    payload = {"name": name}
    if data:
        payload.update(data)
    return netbox.create("ipam/vrfs", payload)


@mcp.tool
def netbox_update_vrf(
    vrf_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Update an existing VRF in NetBox.

    Args:
        vrf_id: The numeric ID of the VRF to update
        data: Fields to update as a dictionary (name, rd, tenant, description, etc.)

    Returns:
        The updated VRF object as a dict
    """
    return netbox.update("ipam/vrfs", vrf_id, data)


@mcp.tool
def netbox_delete_vrf(vrf_id: int) -> bool:
    """
    Delete a VRF from NetBox.

    Args:
        vrf_id: The numeric ID of the VRF to delete

    Returns:
        True if deletion was successful
    """
    return netbox.delete("ipam/vrfs", vrf_id)


@mcp.tool
def netbox_create_prefix(
    prefix: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Create a new prefix in NetBox.

    Args:
        prefix: IP prefix in CIDR notation (required, e.g., "192.168.1.0/24")
        data: Additional optional fields as a dictionary (vrf, tenant, site, status, role, description, etc.)

    Returns:
        The created prefix object as a dict
    """
    payload = {"prefix": prefix}
    if data:
        payload.update(data)
    return netbox.create("ipam/prefixes", payload)


@mcp.tool
def netbox_update_prefix(
    prefix_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Update an existing prefix in NetBox.

    Args:
        prefix_id: The numeric ID of the prefix to update
        data: Fields to update as a dictionary (prefix, vrf, tenant, site, status, etc.)

    Returns:
        The updated prefix object as a dict
    """
    return netbox.update("ipam/prefixes", prefix_id, data)


@mcp.tool
def netbox_delete_prefix(prefix_id: int) -> bool:
    """
    Delete a prefix from NetBox.

    Args:
        prefix_id: The numeric ID of the prefix to delete

    Returns:
        True if deletion was successful
    """
    return netbox.delete("ipam/prefixes", prefix_id)


@mcp.tool
def netbox_create_ip_address(
    address: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Create a new IP address in NetBox.

    Args:
        address: IP address in CIDR notation (required, e.g., "192.168.1.1/24")
        data: Additional optional fields as a dictionary (vrf, tenant, status, dns_name, description, etc.)

    Returns:
        The created IP address object as a dict
    """
    payload = {"address": address}
    if data:
        payload.update(data)
    return netbox.create("ipam/ip-addresses", payload)


@mcp.tool
def netbox_update_ip_address(
    ip_address_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Update an existing IP address in NetBox.

    Args:
        ip_address_id: The numeric ID of the IP address to update
        data: Fields to update as a dictionary (address, vrf, tenant, status, dns_name, etc.)

    Returns:
        The updated IP address object as a dict
    """
    return netbox.update("ipam/ip-addresses", ip_address_id, data)


@mcp.tool
def netbox_delete_ip_address(ip_address_id: int) -> bool:
    """
    Delete an IP address from NetBox.

    Args:
        ip_address_id: The numeric ID of the IP address to delete

    Returns:
        True if deletion was successful
    """
    return netbox.delete("ipam/ip-addresses", ip_address_id)


@mcp.tool
def netbox_create_ip_range(
    start_address: str,
    end_address: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Create a new IP range in NetBox.

    Args:
        start_address: Starting IP address (required)
        end_address: Ending IP address (required)
        data: Additional optional fields as a dictionary (vrf, tenant, status, role, description, etc.)

    Returns:
        The created IP range object as a dict
    """
    payload = {"start_address": start_address, "end_address": end_address}
    if data:
        payload.update(data)
    return netbox.create("ipam/ip-ranges", payload)


@mcp.tool
def netbox_update_ip_range(
    ip_range_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Update an existing IP range in NetBox.

    Args:
        ip_range_id: The numeric ID of the IP range to update
        data: Fields to update as a dictionary (start_address, end_address, vrf, tenant, etc.)

    Returns:
        The updated IP range object as a dict
    """
    return netbox.update("ipam/ip-ranges", ip_range_id, data)


@mcp.tool
def netbox_delete_ip_range(ip_range_id: int) -> bool:
    """
    Delete an IP range from NetBox.

    Args:
        ip_range_id: The numeric ID of the IP range to delete

    Returns:
        True if deletion was successful
    """
    return netbox.delete("ipam/ip-ranges", ip_range_id)


# ============================================================================
# DCIM Objects
# ============================================================================

@mcp.tool
def netbox_create_device(
    name: str,
    device_type: int,
    site: int,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Create a new device in NetBox.

    Args:
        name: Device name (required)
        device_type: Device type ID (required)
        site: Site ID (required)
        data: Additional optional fields as a dictionary (rack, position, face, status, tenant, role, etc.)

    Returns:
        The created device object as a dict
    """
    payload = {"name": name, "device_type": device_type, "site": site}
    if data:
        payload.update(data)
    return netbox.create("dcim/devices", payload)


@mcp.tool
def netbox_update_device(
    device_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Update an existing device in NetBox.

    Args:
        device_id: The numeric ID of the device to update
        data: Fields to update as a dictionary (name, device_type, site, rack, status, etc.)

    Returns:
        The updated device object as a dict
    """
    return netbox.update("dcim/devices", device_id, data)


@mcp.tool
def netbox_delete_device(device_id: int) -> bool:
    """
    Delete a device from NetBox.

    Args:
        device_id: The numeric ID of the device to delete

    Returns:
        True if deletion was successful
    """
    return netbox.delete("dcim/devices", device_id)


@mcp.tool
def netbox_create_interface(
    name: str,
    device: int,
    type: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Create a new interface in NetBox.

    Args:
        name: Interface name (required)
        device: Device ID (required)
        type: Interface type (required, e.g., "1000base-t", "10gbase-x-sfpp", "virtual")
        data: Additional optional fields as a dictionary (enabled, description, mac_address, etc.)

    Returns:
        The created interface object as a dict
    """
    payload = {"name": name, "device": device, "type": type}
    if data:
        payload.update(data)
    return netbox.create("dcim/interfaces", payload)


@mcp.tool
def netbox_update_interface(
    interface_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Update an existing interface in NetBox.

    Args:
        interface_id: The numeric ID of the interface to update
        data: Fields to update as a dictionary (name, device, type, enabled, description, etc.)

    Returns:
        The updated interface object as a dict
    """
    return netbox.update("dcim/interfaces", interface_id, data)


@mcp.tool
def netbox_delete_interface(interface_id: int) -> bool:
    """
    Delete an interface from NetBox.

    Args:
        interface_id: The numeric ID of the interface to delete

    Returns:
        True if deletion was successful
    """
    return netbox.delete("dcim/interfaces", interface_id)


@mcp.tool
def netbox_create_device_type(
    manufacturer: int,
    model: str,
    slug: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Create a new device type in NetBox.

    Args:
        manufacturer: Manufacturer ID (required)
        model: Device model name (required)
        slug: URL-friendly identifier (required)
        data: Additional optional fields as a dictionary (u_height, is_full_depth, part_number, etc.)

    Returns:
        The created device type object as a dict
    """
    payload = {"manufacturer": manufacturer, "model": model, "slug": slug}
    if data:
        payload.update(data)
    return netbox.create("dcim/device-types", payload)


@mcp.tool
def netbox_update_device_type(
    device_type_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Update an existing device type in NetBox.

    Args:
        device_type_id: The numeric ID of the device type to update
        data: Fields to update as a dictionary (manufacturer, model, slug, u_height, etc.)

    Returns:
        The updated device type object as a dict
    """
    return netbox.update("dcim/device-types", device_type_id, data)


@mcp.tool
def netbox_delete_device_type(device_type_id: int) -> bool:
    """
    Delete a device type from NetBox.

    Args:
        device_type_id: The numeric ID of the device type to delete

    Returns:
        True if deletion was successful
    """
    return netbox.delete("dcim/device-types", device_type_id)


@mcp.tool
def netbox_create_manufacturer(
    name: str,
    slug: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Create a new manufacturer in NetBox.

    Args:
        name: Manufacturer name (required)
        slug: URL-friendly identifier (required)
        data: Additional optional fields as a dictionary (description, etc.)

    Returns:
        The created manufacturer object as a dict
    """
    payload = {"name": name, "slug": slug}
    if data:
        payload.update(data)
    return netbox.create("dcim/manufacturers", payload)


@mcp.tool
def netbox_update_manufacturer(
    manufacturer_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Update an existing manufacturer in NetBox.

    Args:
        manufacturer_id: The numeric ID of the manufacturer to update
        data: Fields to update as a dictionary (name, slug, description, etc.)

    Returns:
        The updated manufacturer object as a dict
    """
    return netbox.update("dcim/manufacturers", manufacturer_id, data)


@mcp.tool
def netbox_delete_manufacturer(manufacturer_id: int) -> bool:
    """
    Delete a manufacturer from NetBox.

    Args:
        manufacturer_id: The numeric ID of the manufacturer to delete

    Returns:
        True if deletion was successful
    """
    return netbox.delete("dcim/manufacturers", manufacturer_id)


@mcp.tool
def netbox_create_rack(
    name: str,
    site: int,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Create a new rack in NetBox.

    Args:
        name: Rack name (required)
        site: Site ID (required)
        data: Additional optional fields as a dictionary (facility_id, tenant, status, role, type, u_height, etc.)

    Returns:
        The created rack object as a dict
    """
    payload = {"name": name, "site": site}
    if data:
        payload.update(data)
    return netbox.create("dcim/racks", payload)


@mcp.tool
def netbox_update_rack(
    rack_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Update an existing rack in NetBox.

    Args:
        rack_id: The numeric ID of the rack to update
        data: Fields to update as a dictionary (name, site, facility_id, tenant, status, etc.)

    Returns:
        The updated rack object as a dict
    """
    return netbox.update("dcim/racks", rack_id, data)


@mcp.tool
def netbox_delete_rack(rack_id: int) -> bool:
    """
    Delete a rack from NetBox.

    Args:
        rack_id: The numeric ID of the rack to delete

    Returns:
        True if deletion was successful
    """
    return netbox.delete("dcim/racks", rack_id)


@mcp.tool
def netbox_create_rack_role(
    name: str,
    slug: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Create a new rack role in NetBox.

    Args:
        name: Rack role name (required)
        slug: URL-friendly identifier (required)
        data: Additional optional fields as a dictionary (color, description, etc.)

    Returns:
        The created rack role object as a dict
    """
    payload = {"name": name, "slug": slug}
    if data:
        payload.update(data)
    return netbox.create("dcim/rack-roles", payload)


@mcp.tool
def netbox_create_cable(
    termination_a_type: str,
    termination_a_id: int,
    termination_b_type: str,
    termination_b_id: int,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Create a new cable in NetBox.

    Args:
        termination_a_type: Content type for termination A (e.g., "dcim.interface")
        termination_a_id: ID of termination A
        termination_b_type: Content type for termination B (e.g., "dcim.interface")
        termination_b_id: ID of termination B
        data: Additional optional fields as a dictionary (type, status, label, color, length, etc.)

    Returns:
        The created cable object as a dict
    """
    payload = {
        "termination_a_type": termination_a_type,
        "termination_a_id": termination_a_id,
        "termination_b_type": termination_b_type,
        "termination_b_id": termination_b_id,
    }
    if data:
        payload.update(data)
    return netbox.create("dcim/cables", payload)


@mcp.tool
def netbox_delete_cable(cable_id: int) -> bool:
    """
    Delete a cable from NetBox.

    Args:
        cable_id: The numeric ID of the cable to delete

    Returns:
        True if deletion was successful
    """
    return netbox.delete("dcim/cables", cable_id)


# ============================================================================
# Circuit Objects
# ============================================================================

@mcp.tool
def netbox_create_circuit(
    cid: str,
    provider: int,
    type: int,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Create a new circuit in NetBox.

    Args:
        cid: Circuit ID (required)
        provider: Provider ID (required)
        type: Circuit type ID (required)
        data: Additional optional fields as a dictionary (status, tenant, install_date, commit_rate, etc.)

    Returns:
        The created circuit object as a dict
    """
    payload = {"cid": cid, "provider": provider, "type": type}
    if data:
        payload.update(data)
    return netbox.create("circuits/circuits", payload)


@mcp.tool
def netbox_update_circuit(
    circuit_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Update an existing circuit in NetBox.

    Args:
        circuit_id: The numeric ID of the circuit to update
        data: Fields to update as a dictionary (cid, provider, type, status, tenant, etc.)

    Returns:
        The updated circuit object as a dict
    """
    return netbox.update("circuits/circuits", circuit_id, data)


@mcp.tool
def netbox_delete_circuit(circuit_id: int) -> bool:
    """
    Delete a circuit from NetBox.

    Args:
        circuit_id: The numeric ID of the circuit to delete

    Returns:
        True if deletion was successful
    """
    return netbox.delete("circuits/circuits", circuit_id)


@mcp.tool
def netbox_create_provider(
    name: str,
    slug: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Create a new provider in NetBox.

    Args:
        name: Provider name (required)
        slug: URL-friendly identifier (required)
        data: Additional optional fields as a dictionary (asn, account, portal_url, noc_contact, etc.)

    Returns:
        The created provider object as a dict
    """
    payload = {"name": name, "slug": slug}
    if data:
        payload.update(data)
    return netbox.create("circuits/providers", payload)


@mcp.tool
def netbox_update_provider(
    provider_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Update an existing provider in NetBox.

    Args:
        provider_id: The numeric ID of the provider to update
        data: Fields to update as a dictionary (name, slug, asn, account, etc.)

    Returns:
        The updated provider object as a dict
    """
    return netbox.update("circuits/providers", provider_id, data)


@mcp.tool
def netbox_delete_provider(provider_id: int) -> bool:
    """
    Delete a provider from NetBox.

    Args:
        provider_id: The numeric ID of the provider to delete

    Returns:
        True if deletion was successful
    """
    return netbox.delete("circuits/providers", provider_id)


@mcp.tool
def netbox_create_circuit_type(
    name: str,
    slug: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Create a new circuit type in NetBox.

    Args:
        name: Circuit type name (required)
        slug: URL-friendly identifier (required)
        data: Additional optional fields as a dictionary (description, etc.)

    Returns:
        The created circuit type object as a dict
    """
    payload = {"name": name, "slug": slug}
    if data:
        payload.update(data)
    return netbox.create("circuits/circuit-types", payload)


@mcp.tool
def netbox_update_circuit_type(
    circuit_type_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Update an existing circuit type in NetBox.

    Args:
        circuit_type_id: The numeric ID of the circuit type to update
        data: Fields to update as a dictionary (name, slug, description, etc.)

    Returns:
        The updated circuit type object as a dict
    """
    return netbox.update("circuits/circuit-types", circuit_type_id, data)


@mcp.tool
def netbox_delete_circuit_type(circuit_type_id: int) -> bool:
    """
    Delete a circuit type from NetBox.

    Args:
        circuit_type_id: The numeric ID of the circuit type to delete

    Returns:
        True if deletion was successful
    """
    return netbox.delete("circuits/circuit-types", circuit_type_id)


# ============================================================================
# Virtualization Objects
# ============================================================================

@mcp.tool
def netbox_create_virtual_machine(
    name: str,
    cluster: int,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Create a new virtual machine in NetBox.

    Args:
        name: Virtual machine name (required)
        cluster: Cluster ID (required)
        data: Additional optional fields as a dictionary (status, role, tenant, platform, vcpus, memory, disk, etc.)

    Returns:
        The created virtual machine object as a dict
    """
    payload = {"name": name, "cluster": cluster}
    if data:
        payload.update(data)
    return netbox.create("virtualization/virtual-machines", payload)


@mcp.tool
def netbox_update_virtual_machine(
    vm_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Update an existing virtual machine in NetBox.

    Args:
        vm_id: The numeric ID of the virtual machine to update
        data: Fields to update as a dictionary (name, cluster, status, role, tenant, etc.)

    Returns:
        The updated virtual machine object as a dict
    """
    return netbox.update("virtualization/virtual-machines", vm_id, data)


@mcp.tool
def netbox_delete_virtual_machine(vm_id: int) -> bool:
    """
    Delete a virtual machine from NetBox.

    Args:
        vm_id: The numeric ID of the virtual machine to delete

    Returns:
        True if deletion was successful
    """
    return netbox.delete("virtualization/virtual-machines", vm_id)


@mcp.tool
def netbox_create_cluster(
    name: str,
    type: int,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Create a new cluster in NetBox.

    Args:
        name: Cluster name (required)
        type: Cluster type ID (required)
        data: Additional optional fields as a dictionary (group, status, tenant, site, etc.)

    Returns:
        The created cluster object as a dict
    """
    payload = {"name": name, "type": type}
    if data:
        payload.update(data)
    return netbox.create("virtualization/clusters", payload)


@mcp.tool
def netbox_update_cluster(
    cluster_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Update an existing cluster in NetBox.

    Args:
        cluster_id: The numeric ID of the cluster to update
        data: Fields to update as a dictionary (name, type, group, status, tenant, etc.)

    Returns:
        The updated cluster object as a dict
    """
    return netbox.update("virtualization/clusters", cluster_id, data)


@mcp.tool
def netbox_delete_cluster(cluster_id: int) -> bool:
    """
    Delete a cluster from NetBox.

    Args:
        cluster_id: The numeric ID of the cluster to delete

    Returns:
        True if deletion was successful
    """
    return netbox.delete("virtualization/clusters", cluster_id)


def _endpoint_for_type(object_type: str) -> str:
    """
    Returns partial API endpoint prefix for the given object type.
    e.g., "dcim.device" -> "dcim/devices"
    """
    return NETBOX_OBJECT_TYPES[object_type]['endpoint']



def main() -> None:
    """Main entry point for the MCP server."""
    global netbox

    cli_overlay: dict[str, Any] = parse_cli_args()

    try:
        settings = Settings(**cli_overlay)
    except Exception as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    configure_logging(settings.log_level)
    logger = logging.getLogger(__name__)

    logger.info("Starting NetBox MCP Server")
    logger.info(f"Effective configuration: {settings.get_effective_config_summary()}")

    if not settings.verify_ssl:
        logger.warning(
            "SSL certificate verification is DISABLED. "
            "This is insecure and should only be used for testing."
        )

    if settings.transport == "http" and settings.host in ["0.0.0.0", "::", "[::]"]:
        logger.warning(
            f"HTTP transport is bound to {settings.host}:{settings.port}, which exposes the service to all network interfaces (IPv4/IPv6). "
            "This is insecure and should only be used for testing. Ensure this is secured with TLS/reverse proxy if exposed to network."
        )
    elif settings.transport == "http" and settings.host not in [
        "127.0.0.1",
        "localhost",
    ]:
        logger.info(
            f"HTTP transport is bound to {settings.host}:{settings.port}. "
            "Ensure this is secured with TLS/reverse proxy if exposed to network."
        )

    try:
        netbox = NetBoxRestClient(
            url=str(settings.netbox_url),
            token=settings.netbox_token.get_secret_value(),
            verify_ssl=settings.verify_ssl,
        )
        logger.debug("NetBox client initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize NetBox client: {e}")
        sys.exit(1)

    try:
        if settings.transport == "stdio":
            logger.info("Starting stdio transport")
            mcp.run(transport="stdio")
        elif settings.transport == "http":
            logger.info(f"Starting HTTP transport on {settings.host}:{settings.port}")
            mcp.run(transport="http", host=settings.host, port=settings.port)
    except Exception as e:
        logger.error(f"Failed to start MCP server: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
