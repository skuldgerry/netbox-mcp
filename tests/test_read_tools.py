"""Regression tests for the upstream-derived read-tool behavior."""

from collections.abc import Iterator
from contextlib import contextmanager

import pytest

import netbox_mcp_server.server as server


class RecordingReadClient:
    def __init__(self, failing_endpoint: str | None = None) -> None:
        self.calls: list[dict] = []
        self.failing_endpoint = failing_endpoint

    def get(
        self,
        endpoint: str,
        id: int | None = None,
        params: dict | None = None,
        fallback_endpoint: str | None = None,
    ) -> dict:
        self.calls.append(
            {
                "endpoint": endpoint,
                "id": id,
                "params": params,
                "fallback_endpoint": fallback_endpoint,
            }
        )
        if endpoint == self.failing_endpoint:
            raise RuntimeError("simulated unsupported search endpoint")
        return {
            "count": 1,
            "next": None,
            "previous": None,
            "results": [{"id": id or 1, "name": "example"}],
        }


@contextmanager
def installed_client(client: RecordingReadClient) -> Iterator[RecordingReadClient]:
    previous_client = server.netbox
    server.netbox = client
    try:
        yield client
    finally:
        server.netbox = previous_client


def test_get_objects_forwards_pagination_projection_brief_and_ordering() -> None:
    with installed_client(RecordingReadClient()) as client:
        response = server.netbox_get_objects(
            "dcim.device",
            {"site_id": 7},
            fields=["id", "name"],
            brief=True,
            limit=10,
            offset=20,
            ordering=["name", "-id"],
        )

    assert response["count"] == 1
    assert client.calls == [
        {
            "endpoint": "dcim/devices",
            "id": None,
            "params": {
                "site_id": 7,
                "limit": 10,
                "offset": 20,
                "fields": "id,name",
                "brief": "1",
                "ordering": "name,-id",
            },
            "fallback_endpoint": None,
        }
    ]


@pytest.mark.parametrize("ordering", [None, "", [], [""]])
def test_blank_ordering_is_not_forwarded(ordering: str | list[str] | None) -> None:
    with installed_client(RecordingReadClient()) as client:
        server.netbox_get_objects("dcim.site", {}, ordering=ordering)
    assert "ordering" not in client.calls[0]["params"]


@pytest.mark.parametrize(
    "filters",
    [
        {"name__ic": "switch"},
        {"id__in": [1, 2]},
        {"site_id": 3},
    ],
)
def test_supported_filters_are_accepted(filters: dict) -> None:
    server.validate_filters(filters)


@pytest.mark.parametrize("field", ["device__site_id", "device__site__name", "name__bad"])
def test_multihop_or_unknown_filter_lookups_are_rejected(field: str) -> None:
    with pytest.raises(ValueError, match="Multi-hop relationship"):
        server.validate_filters({field: "value"})


def test_get_object_by_id_forwards_version_fallback() -> None:
    with installed_client(RecordingReadClient()) as client:
        server.netbox_get_object_by_id("core.objecttype", 9, fields=["id", "name"])
    assert client.calls == [
        {
            "endpoint": "core/object-types",
            "id": 9,
            "params": {"fields": "id,name"},
            "fallback_endpoint": "extras/object-types",
        }
    ]


def test_search_keeps_other_types_when_one_endpoint_fails() -> None:
    client = RecordingReadClient(failing_endpoint="dcim/devices")
    with installed_client(client):
        result = server.netbox_search_objects(
            "edge",
            object_types=["dcim.device", "dcim.site"],
            fields=["id", "name"],
        )
    assert result["dcim.device"] == []
    assert result["dcim.site"] == [{"id": 1, "name": "example"}]


def test_unknown_object_type_is_rejected_before_client_call() -> None:
    with (
        installed_client(RecordingReadClient()) as client,
        pytest.raises(ValueError, match="Invalid object_type"),
    ):
        server.netbox_get_objects("not.real", {})
    assert client.calls == []
