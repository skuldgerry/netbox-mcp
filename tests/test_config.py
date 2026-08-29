"""Tests for HTTP auth configuration and CLI overlays."""

import sys
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from netbox_mcp_server.config import Settings
from netbox_mcp_server.server import parse_cli_args


def test_auth_token_read_from_env() -> None:
    with patch.dict(
        "os.environ",
        {
            "NETBOX_URL": "https://netbox.example.com/",
            "NETBOX_TOKEN": "tok",
            "MCP_AUTH_TOKEN": "bearer-secret",
        },
        clear=True,
    ):
        settings = Settings(_env_file=None)

    assert settings.mcp_auth_token is not None
    assert settings.mcp_auth_token.get_secret_value() == "bearer-secret"


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_auth_token_normalized_to_none(blank: str) -> None:
    settings = Settings(
        netbox_url="https://netbox.example.com/",
        netbox_token="tok",
        mcp_auth_token=blank,
        _env_file=None,
    )
    assert settings.mcp_auth_token is None


def test_auth_token_masked_in_summary() -> None:
    settings = Settings(
        netbox_url="https://netbox.example.com/",
        netbox_token="tok",
        transport="http",
        mcp_auth_token="bearer-secret",
        _env_file=None,
    )
    summary = settings.get_effective_config_summary()
    assert summary["mcp_auth_token"] == "***REDACTED***"
    assert "bearer-secret" not in str(summary)


def test_parse_cli_args_mcp_auth_token() -> None:
    with patch.object(sys, "argv", ["server.py", "--mcp-auth-token", "bearer-secret"]):
        result = parse_cli_args()
    assert result["mcp_auth_token"] == "bearer-secret"


def test_parse_cli_args_cors_origins() -> None:
    argv = [
        "server.py",
        "--cors-origins",
        "https://one.example",
        "--cors-origins",
        "https://two.example",
    ]
    with patch.object(sys, "argv", argv):
        result = parse_cli_args()
    assert result["cors_origins"] == ["https://one.example", "https://two.example"]


def test_plugin_discovery_and_write_rules_read_from_env() -> None:
    with patch.dict(
        "os.environ",
        {
            "NETBOX_URL": "https://netbox.example.com/",
            "NETBOX_TOKEN": "tok",
            "ENABLE_PLUGIN_DISCOVERY": "true",
            "PLUGIN_WRITE_RULES": '{"netbox_dns.zone":["create","update"]}',
        },
        clear=True,
    ):
        settings = Settings(_env_file=None)

    assert settings.enable_plugin_discovery is True
    assert settings.plugin_write_rules == {"netbox_dns.zone": {"create", "update"}}


def test_plugin_write_rules_require_discovery() -> None:
    with pytest.raises(ValidationError, match="ENABLE_PLUGIN_DISCOVERY=true"):
        Settings(
            netbox_url="https://netbox.example.com/",
            netbox_token="tok",
            plugin_write_rules={"netbox_dns.zone": {"create"}},
            _env_file=None,
        )


@pytest.mark.parametrize("object_type", ["netbox_dns", "netbox_dns.*", "netbox-dns.zone"])
def test_plugin_write_rules_require_exact_dotted_types(object_type: str) -> None:
    with pytest.raises(ValidationError, match="exact dotted object types"):
        Settings(
            netbox_url="https://netbox.example.com/",
            netbox_token="tok",
            enable_plugin_discovery=True,
            plugin_write_rules={object_type: {"create"}},
            _env_file=None,
        )


def test_plugin_write_rules_reject_invalid_operation() -> None:
    with pytest.raises(ValidationError, match="Input should be"):
        Settings(
            netbox_url="https://netbox.example.com/",
            netbox_token="tok",
            enable_plugin_discovery=True,
            plugin_write_rules={"netbox_dns.zone": {"read"}},
            _env_file=None,
        )


def test_plugin_write_rules_reject_empty_operation_set() -> None:
    with pytest.raises(ValidationError, match="at least one operation"):
        Settings(
            netbox_url="https://netbox.example.com/",
            netbox_token="tok",
            enable_plugin_discovery=True,
            plugin_write_rules={"netbox_dns.zone": set()},
            _env_file=None,
        )


def test_parse_cli_args_merges_plugin_write_rules() -> None:
    argv = [
        "server.py",
        "--enable-plugin-discovery",
        "--plugin-write",
        "netbox_dns.zone:create,update",
        "--plugin-write",
        "netbox_dns.zone:delete",
    ]
    with patch.object(sys, "argv", argv):
        result = parse_cli_args()

    assert result["enable_plugin_discovery"] is True
    assert result["plugin_write_rules"] == {"netbox_dns.zone": {"create", "update", "delete"}}


def test_parse_cli_args_rejects_invalid_plugin_operation() -> None:
    with (
        patch.object(sys, "argv", ["server.py", "--plugin-write", "netbox_dns.zone:read"]),
        pytest.raises(SystemExit),
    ):
        parse_cli_args()
