"""Tests for opt-in plugin discovery and operation-specific write controls."""

import asyncio
from collections.abc import Iterator

import httpx
import pytest

import netbox_mcp_server.server as server


@pytest.fixture(autouse=True)
def isolate_plugin_registries() -> Iterator[None]:
    previous_types = dict(server.DISCOVERED_PLUGIN_OBJECT_TYPES)
    previous_rules = {
        object_type: set(operations)
        for object_type, operations in server.PLUGIN_WRITE_RULES.items()
    }
    server.DISCOVERED_PLUGIN_OBJECT_TYPES.clear()
    server.PLUGIN_WRITE_RULES.clear()
    try:
        yield
    finally:
        server.DISCOVERED_PLUGIN_OBJECT_TYPES.clear()
        server.DISCOVERED_PLUGIN_OBJECT_TYPES.update(previous_types)
        server.PLUGIN_WRITE_RULES.clear()
        server.PLUGIN_WRITE_RULES.update(previous_rules)


def plugin_type(
    app_label: str = "netbox_dns",
    model: str = "zone",
    endpoint: str = "/api/plugins/netbox-dns/zones/",
) -> dict[str, object]:
    return {
        "app_label": app_label,
        "model": model,
        "display": "Zone",
        "is_plugin_model": True,
        "rest_api_endpoint": endpoint,
    }


class DiscoveryClient:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = iter(responses)
        self.calls: list[tuple[str, dict[str, int], str]] = []

    def get(
        self,
        endpoint: str,
        params: dict[str, int],
        fallback_endpoint: str,
    ) -> dict[str, object]:
        self.calls.append((endpoint, params, fallback_endpoint))
        return next(self.responses)


def test_discovers_and_normalizes_plugin_rest_endpoints() -> None:
    client = DiscoveryClient([{"results": [plugin_type()], "next": None}])

    result = server.discover_plugin_types(client)  # type: ignore[arg-type]

    assert result == {"netbox_dns.zone": {"name": "Zone", "endpoint": "plugins/netbox-dns/zones"}}
    assert client.calls == [
        ("core/object-types", {"limit": 100, "offset": 0}, "extras/object-types")
    ]


def test_discovery_pages_until_next_is_empty() -> None:
    client = DiscoveryClient(
        [
            {"results": [plugin_type()], "next": "next-page"},
            {
                "results": [
                    plugin_type(
                        app_label="netbox_dns",
                        model="record",
                        endpoint="plugins/netbox-dns/records/",
                    )
                ],
                "next": None,
            },
        ]
    )

    result = server.discover_plugin_types(client)  # type: ignore[arg-type]

    assert set(result) == {"netbox_dns.zone", "netbox_dns.record"}
    assert client.calls[1][1] == {"limit": 100, "offset": 100}


def test_discovery_skips_unsafe_or_unusable_entries() -> None:
    non_plugin = plugin_type(model="not_plugin")
    non_plugin["is_plugin_model"] = False
    missing_endpoint = plugin_type(model="missing")
    missing_endpoint["rest_api_endpoint"] = None
    rows = [
        non_plugin,
        missing_endpoint,
        plugin_type(app_label="dcim", model="site"),
        plugin_type(model="outside", endpoint="/api/dcim/devices/"),
    ]

    result = server.discover_plugin_types(  # type: ignore[arg-type]
        DiscoveryClient([{"results": rows, "next": None}])
    )

    assert result == {}


def test_discovery_failure_leaves_core_registry_usable() -> None:
    class FailingClient:
        def get(self, *_args: object, **_kwargs: object) -> dict[str, object]:
            raise httpx.ConnectError("offline")

    assert server.discover_plugin_types(FailingClient()) == {}  # type: ignore[arg-type]
    assert "dcim.site" in server.get_readable_object_types()


def test_activation_enables_reads_but_keeps_plugin_writes_disabled_by_default() -> None:
    discovered = {"netbox_dns.zone": {"name": "Zone", "endpoint": "plugins/netbox-dns/zones"}}

    undiscovered = server.activate_plugin_types(discovered, {})

    assert undiscovered == set()
    assert server.get_read_endpoint_info("netbox_dns.zone") == (
        "plugins/netbox-dns/zones",
        None,
    )
    for operation in server.PLUGIN_WRITE_OPERATIONS:
        with pytest.raises(ValueError, match="is not enabled"):
            server.get_writable_endpoint("netbox_dns.zone", operation)


def test_activation_allows_only_explicit_plugin_operations() -> None:
    discovered = {"netbox_dns.zone": {"name": "Zone", "endpoint": "plugins/netbox-dns/zones"}}
    server.activate_plugin_types(discovered, {"netbox_dns.zone": {"create", "update"}})

    assert server.get_writable_endpoint("netbox_dns.zone", "create") == "plugins/netbox-dns/zones"
    assert server.get_writable_endpoint("netbox_dns.zone", "update") == "plugins/netbox-dns/zones"
    with pytest.raises(ValueError, match=r"delete.*not enabled"):
        server.get_writable_endpoint("netbox_dns.zone", "delete")


def test_unknown_plugin_rule_remains_disabled() -> None:
    undiscovered = server.activate_plugin_types({}, {"netbox_dns.zone": {"create"}})

    assert undiscovered == {"netbox_dns.zone"}
    assert server.PLUGIN_WRITE_RULES == {}


def test_core_types_remain_writable_without_plugin_rules() -> None:
    server.activate_plugin_types({}, {})
    assert server.get_writable_endpoint("dcim.site", "delete") == "dcim/sites"


def test_plugin_write_rules_reject_core_types() -> None:
    with pytest.raises(ValueError, match="applies only to discovered plugin types"):
        server.activate_plugin_types({}, {"dcim.site": {"create"}})


def test_unknown_type_and_operation_are_rejected() -> None:
    with pytest.raises(ValueError, match="neither a core type nor a discovered plugin type"):
        server.get_writable_endpoint("unknown.widget", "create")
    with pytest.raises(ValueError, match="Unsupported write operation"):
        server.get_writable_endpoint("dcim.site", "read")


def test_generic_write_tool_enforces_plugin_operation_rule() -> None:
    class RecordingClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def create(self, endpoint: str, data: dict[str, object]) -> dict[str, object]:
            self.calls.append((endpoint, data))
            return {"id": 1, **data}

    discovered = {"netbox_dns.zone": {"name": "Zone", "endpoint": "plugins/netbox-dns/zones"}}
    server.activate_plugin_types(discovered, {"netbox_dns.zone": {"create"}})
    client = RecordingClient()
    previous_client = server.netbox
    server.netbox = client
    try:
        assert server.netbox_create_object("netbox_dns.zone", {"name": "example.com"}) == {
            "id": 1,
            "name": "example.com",
        }
        with pytest.raises(ValueError, match=r"delete.*not enabled"):
            server.netbox_delete_object("netbox_dns.zone", 1)
    finally:
        server.netbox = previous_client

    assert client.calls == [("plugins/netbox-dns/zones", {"name": "example.com"})]


def test_discovered_type_is_added_to_read_tool_description() -> None:
    discovered = {"netbox_dns.zone": {"name": "Zone", "endpoint": "plugins/netbox-dns/zones"}}
    server.activate_plugin_types(discovered, {})
    try:
        asyncio.run(server.update_read_tool_descriptions())
        tool = asyncio.run(server.mcp.get_tool("netbox_get_objects"))
        assert tool is not None
        assert "netbox_dns.zone" in tool.description
    finally:
        server.activate_plugin_types({}, {})
        asyncio.run(server.update_read_tool_descriptions())
