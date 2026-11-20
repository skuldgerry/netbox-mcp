"""Run inside the candidate container; all traffic stays on its loopback."""

import asyncio
import json
import os
import ssl
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import IPv4Address
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import urlopen

import httpx
import httpx2
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from mcp import Client, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client

from netbox_mcp_server.netbox_client import NetBoxRestClient

MCP_URL = "http://127.0.0.1:8000/mcp"
BEARER = {"Authorization": "Bearer smoke-mcp-token"}
LEGACY_VERSIONS = ("2025-06-18", "2025-11-25")
MODERN_VERSION = "2026-07-28"
READ_TOOL = "netbox_get_objects"
READ_ARGUMENTS = {"object_type": "dcim.device", "filters": {}, "limit": 1}


class FakeNetBox(BaseHTTPRequestHandler):
    """Serve exactly one read fixture and reject every other route/method."""

    reads = 0

    def do_GET(self):
        if (
            self.path.split("?")[0] != "/api/dcim/devices/"
            or self.headers.get("Authorization") != "Token smoke-netbox-token"
        ):
            self.send_error(403)
            return
        type(self).reads += 1
        body = json.dumps(
            {
                "count": 1,
                "next": None,
                "previous": None,
                "results": [{"id": 1, "name": "smoke-device"}],
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def rpc_message(method, request_id=None, params=None):
    message = {"jsonrpc": "2.0", "method": method}
    if request_id is not None:
        message["id"] = request_id
    if params is not None:
        message["params"] = params
    return message


def legacy_response(response, request_id):
    if response.headers["content-type"].partition(";")[0] == "application/json":
        response.read()
        return response.json()

    data = []
    for line in response.iter_lines():
        if line.startswith("data:"):
            data.append(line.removeprefix("data:").removeprefix(" "))
        elif not line and data:
            payload = json.loads("\n".join(data))
            data.clear()
            if payload.get("id") == request_id:
                return payload
    raise RuntimeError(f"No MCP response for request {request_id}")


def legacy_call(client, request_id, method, params=None):
    with client.stream("POST", MCP_URL, json=rpc_message(method, request_id, params)) as response:
        response.raise_for_status()
        payload = legacy_response(response, request_id)
        if payload.get("id") != request_id or "result" not in payload:
            raise RuntimeError(f"MCP {method} failed: {payload}")
        return payload["result"], response.headers


def initialize_legacy(client, version):
    client.headers.pop("mcp-session-id", None)
    client.headers.pop("mcp-protocol-version", None)
    result, headers = legacy_call(
        client,
        1,
        "initialize",
        {
            "protocolVersion": version,
            "capabilities": {},
            "clientInfo": {"name": "netbox-smoke", "version": "1"},
        },
    )
    if result["protocolVersion"] != version or "mcp-session-id" not in headers:
        raise RuntimeError(f"MCP did not negotiate a stateful {version} session")
    session_id = headers["mcp-session-id"]
    client.headers.update({"mcp-session-id": session_id, "mcp-protocol-version": version})
    client.post(MCP_URL, json=rpc_message("notifications/initialized")).raise_for_status()
    return session_id


def verify_catalog(tool_names):
    if READ_TOOL not in tool_names:
        raise RuntimeError("Read tool missing from MCP catalog")


def verify_fixture_read(result, reads_before):
    if result.get("isError") or "smoke-device" not in json.dumps(result):
        raise RuntimeError("Read tool did not return the NetBox fixture")
    if FakeNetBox.reads != reads_before + 1:
        raise RuntimeError("Read tool did not use the isolated NetBox fixture")


def probe_legacy():
    with httpx.Client(
        headers={"Accept": "application/json, text/event-stream"}, timeout=5
    ) as client:
        for token in (None, "wrong-token"):
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            response = client.post(
                MCP_URL,
                headers=headers,
                json=rpc_message("initialize", 1, {}),
            )
            if response.status_code not in {401, 403}:
                raise RuntimeError(f"MCP accepted missing/invalid auth: {response.status_code}")
        client.headers.update(BEARER)
        for version in LEGACY_VERSIONS:
            expired_session = initialize_legacy(client, version)
            catalog, _ = legacy_call(client, 2, "tools/list")
            verify_catalog(tool["name"] for tool in catalog["tools"])
            reads_before = FakeNetBox.reads
            result, _ = legacy_call(
                client, 3, "tools/call", {"name": READ_TOOL, "arguments": READ_ARGUMENTS}
            )
            verify_fixture_read(result, reads_before)
            # The disposable container uses a three-second idle timeout.
            time.sleep(4)
            response = client.post(MCP_URL, json=rpc_message("ping", 4))
            if response.status_code != 404:
                raise RuntimeError(
                    f"{version} idle session was not rejected: {response.status_code}"
                )

            if initialize_legacy(client, version) == expired_session:
                raise RuntimeError(f"{version} reconnect reused the expired session ID")
            legacy_call(client, 2, "ping")
            client.delete(MCP_URL).raise_for_status()
            print(f"PASS: HTTP {version} catalog, read, session expiry and reconnect")

        response = client.options(
            MCP_URL,
            headers={
                "Origin": "https://smoke.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,mcp-protocol-version,mcp-method,mcp-name",
            },
        )
        if response.status_code != 200 or response.headers.get("access-control-allow-origin") != (
            "https://smoke.example"
        ):
            raise RuntimeError("CORS preflight rejected modern MCP headers")


async def probe_sdk_client(client, version):
    async with client:
        if client.protocol_version != version:
            raise RuntimeError(f"Expected MCP {version}, negotiated {client.protocol_version}")
        catalog = await client.list_tools()
        verify_catalog(tool.name for tool in catalog.tools)
        reads_before = FakeNetBox.reads
        result = await client.call_tool(READ_TOOL, READ_ARGUMENTS)
        verify_fixture_read(result.model_dump(mode="json", by_alias=True), reads_before)


async def probe_modern_and_stdio():
    async with httpx2.AsyncClient(headers=BEARER, timeout=5) as http_client:
        transport = streamable_http_client(MCP_URL, http_client=http_client)
        await probe_sdk_client(Client(transport, read_timeout_seconds=5), MODERN_VERSION)
        print(f"PASS: HTTP {MODERN_VERSION} authenticated catalog and read")

    stdio = StdioServerParameters(
        command=sys.executable,
        args=["-m", "netbox_mcp_server.server"],
        env={**os.environ, "TRANSPORT": "stdio"},
    )
    for mode, version in (("legacy", LEGACY_VERSIONS[-1]), ("auto", MODERN_VERSION)):
        await probe_sdk_client(Client(stdio, mode=mode, read_timeout_seconds=5), version)
        print(f"PASS: stdio {version} catalog and read")


def probe_netbox_tls():
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "smoke-netbox")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(IPv4Address("127.0.0.1"))]), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    with TemporaryDirectory() as directory:
        cert_path = Path(directory) / "cert.pem"
        key_path = Path(directory) / "key.pem"
        cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.minimum_version = ssl.TLSVersion.TLSv1_2
        tls.load_cert_chain(cert_path, key_path)
        with ThreadingHTTPServer(("127.0.0.1", 0), FakeNetBox) as server:
            server.socket = tls.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f"https://127.0.0.1:{server.server_port}"
            try:
                client = NetBoxRestClient(url, "smoke-netbox-token")
                with client.session:
                    try:
                        client.get("dcim/devices")
                    except httpx.ConnectError as error:
                        if "CERTIFICATE_VERIFY_FAILED" not in str(error):
                            raise
                    else:
                        raise RuntimeError("NetBox client accepted an untrusted certificate")
                with patch.dict(os.environ, {"SSL_CERT_FILE": str(cert_path)}):
                    client = NetBoxRestClient(url, "smoke-netbox-token")
                    with client.session:
                        result = client.get("dcim/devices")
                    if result["results"] != [{"id": 1, "name": "smoke-device"}]:
                        raise RuntimeError("NetBox client did not return the trusted TLS fixture")
            finally:
                server.shutdown()


def main():
    for _ in range(45):
        try:
            with urlopen("http://127.0.0.1:8000/health", timeout=2) as response:
                if response.read() == b"OK":
                    break
        except (URLError, TimeoutError):
            pass
        time.sleep(1)
    else:
        raise RuntimeError("Container health endpoint did not become ready")
    server = ThreadingHTTPServer(("127.0.0.1", 18081), FakeNetBox)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        probe_legacy()
        asyncio.run(probe_modern_and_stdio())
    finally:
        server.shutdown()
        server.server_close()
    probe_netbox_tls()
    print("PASS: health, MCP authentication, CORS and NetBox TLS")


if __name__ == "__main__":
    main()
