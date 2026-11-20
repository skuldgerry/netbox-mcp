"""Run inside the candidate container; all traffic stays on its loopback."""

import asyncio
import json
import os
import ssl
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
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from netbox_mcp_server.netbox_client import NetBoxRestClient


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


async def probe():
    url = "http://127.0.0.1:8000/mcp"
    async with httpx.AsyncClient() as client:
        for token in (None, "wrong-token"):
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            response = await client.post(
                url,
                headers=headers,
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            )
            if response.status_code not in {401, 403}:
                raise RuntimeError(f"MCP accepted missing/invalid auth: {response.status_code}")
    async with (
        httpx.AsyncClient(headers={"Authorization": "Bearer smoke-mcp-token"}) as client,
        streamable_http_client(url, http_client=client) as (read, write, get_session_id),
        ClientSession(read, write) as session,
    ):
        initialized = await session.initialize()
        session_id = get_session_id()
        if not session_id:
            raise RuntimeError("MCP did not establish a session")
        tools = await session.list_tools()
        if "netbox_get_objects" not in {tool.name for tool in tools.tools}:
            raise RuntimeError("Read tool missing from MCP catalog")
        result = await session.call_tool(
            "netbox_get_objects", {"object_type": "dcim.device", "filters": {}, "limit": 1}
        )
        if result.isError or "smoke-device" not in result.model_dump_json():
            raise RuntimeError("Read tool did not return the NetBox fixture")
        if FakeNetBox.reads != 1:
            raise RuntimeError("Read tool did not use the isolated NetBox fixture")

    async with httpx.AsyncClient(headers={"Authorization": "Bearer smoke-mcp-token"}) as client:
        response = await client.post(
            url,
            headers={
                "Accept": "application/json, text/event-stream",
                "Mcp-Session-Id": session_id,
                "Mcp-Protocol-Version": initialized.protocolVersion,
            },
            json={"jsonrpc": "2.0", "id": 2, "method": "ping"},
        )
        if response.status_code != 404:
            raise RuntimeError(f"Closed MCP session was not rejected: {response.status_code}")
        async with (
            streamable_http_client(url, http_client=client) as (read, write, get_session_id),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            if get_session_id() in {None, session_id}:
                raise RuntimeError("Reconnect did not establish a new MCP session")
            await session.send_ping()


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
        asyncio.run(probe())
    finally:
        server.shutdown()
        server.server_close()
    probe_netbox_tls()
    print("PASS: health, MCP authentication, catalog, fixture read, reconnect and NetBox TLS")


if __name__ == "__main__":
    main()
