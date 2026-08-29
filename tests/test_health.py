"""Tests for the container liveness route."""

from starlette.testclient import TestClient

from netbox_mcp_server.server import mcp


def test_health_route_is_available_without_mcp_session() -> None:
    with TestClient(mcp.http_app()) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.text == "OK"
