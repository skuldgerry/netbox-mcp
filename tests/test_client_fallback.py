"""Tests for NetBox-version endpoint fallback support."""

import httpx

from netbox_mcp_server.netbox_client import NetBoxRestClient


def test_get_retries_fallback_endpoint_after_404() -> None:
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path.startswith("/api/core/object-types"):
            return httpx.Response(404)
        return httpx.Response(200, json={"id": 3})

    client = NetBoxRestClient("https://netbox.example.com", "token")
    client.session.close()
    client.session = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = client.get(
            "core/object-types",
            id=3,
            fallback_endpoint="extras/object-types",
        )
    finally:
        client.session.close()

    assert result == {"id": 3}
    assert requested_paths == [
        "/api/core/object-types/3/",
        "/api/extras/object-types/3/",
    ]
