"""Run inside the candidate container; all traffic stays on its loopback."""

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import URLError
from urllib.request import urlopen

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


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
        streamable_http_client(url, http_client=client) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
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
    print("PASS: health, authentication rejection, MCP initialize/catalog and fixture read")


if __name__ == "__main__":
    main()
