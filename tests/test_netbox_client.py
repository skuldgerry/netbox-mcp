"""Tests for NetBox API authentication and CRUD request routing."""

import httpx
import pytest

from netbox_mcp_server.netbox_client import NetBoxRestClient


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("legacy-token", "Token legacy-token"),
        ("nbt_v2-token", "Bearer nbt_v2-token"),
    ],
)
def test_netbox_auth_scheme(token: str, expected: str) -> None:
    client = NetBoxRestClient("https://netbox.example.com", token)
    try:
        assert client.session.headers["Authorization"] == expected
    finally:
        client.session.close()


def test_crud_methods_use_collection_and_detail_urls() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, json={"id": 7})

    client = NetBoxRestClient("https://netbox.example.com", "legacy-token")
    client.session.close()
    client.session = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        client.create("dcim/sites", {"name": "Site"})
        client.update("dcim/sites", 7, {"name": "Updated"})
        assert client.delete("dcim/sites", 7) is True
    finally:
        client.session.close()

    assert [(r.method, r.url.path) for r in requests] == [
        ("POST", "/api/dcim/sites/"),
        ("PATCH", "/api/dcim/sites/7/"),
        ("DELETE", "/api/dcim/sites/7/"),
    ]


def test_bulk_methods_use_collection_url_without_bulk_suffix() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, json=[{"id": 7}])

    client = NetBoxRestClient("https://netbox.example.com", "legacy-token")
    client.session.close()
    client.session = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        client.bulk_create("dcim/sites", [{"name": "Site"}])
        client.bulk_update("dcim/sites", [{"id": 7, "name": "Updated"}])
        assert client.bulk_delete("dcim/sites", [7]) is True
    finally:
        client.session.close()

    assert [(r.method, r.url.path) for r in requests] == [
        ("POST", "/api/dcim/sites/"),
        ("PATCH", "/api/dcim/sites/"),
        ("DELETE", "/api/dcim/sites/"),
    ]
