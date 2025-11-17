# NetBox MCP Enhanced

> **Enhanced version** of the official [NetBox MCP Server](https://github.com/netboxlabs/netbox-mcp-server) with comprehensive write operations support.

This is an enhanced [Model Context Protocol](https://modelcontextprotocol.io/) server for NetBox that enables you to interact with your NetBox data directly via LLMs that support MCP. It supports both **read and write operations**, allowing you to create, update, and delete NetBox objects through natural language prompts.

## What's Enhanced?

This version extends the official NetBox MCP server with:
- ✅ **50+ write tools** for creating, updating, and deleting NetBox objects
- ✅ **Priority support** for Sites, Tenants, Tags, and VLANs
- ✅ **Docker Compose** deployment without requiring `.env` files
- ✅ **HTTP transport** support for web clients (OpenWebUI, n8n)
- ✅ **Generic tools** for any NetBox object type

Based on the official [netbox-mcp-server](https://github.com/netboxlabs/netbox-mcp-server) project.

## Quick Start

See the full [README.md](README.md) for complete documentation.

**Docker Compose:**
```bash
# Update NETBOX_URL and NETBOX_TOKEN in docker-compose.yml
docker-compose up -d
```

The server will be accessible at `http://localhost:8000/mcp` for MCP clients.