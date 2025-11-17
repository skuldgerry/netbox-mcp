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

## Tools

### Read Operations

| Tool | Description |
|------|-------------|
| `netbox_get_objects` | Retrieves NetBox core objects based on their type and filters |
| `netbox_get_object_by_id` | Gets detailed information about a specific NetBox object by its ID |
| `netbox_get_changelogs` | Retrieves change history records (audit trail) based on filters |
| `netbox_search_objects` | Performs global search across multiple NetBox object types |

### Write Operations

The server includes comprehensive write operations for managing NetBox objects. All write operations support create, update, and delete operations.

#### Priority Objects (Sites, Tenants, Tags, VLANs)

| Tool | Description |
|------|-------------|
| `netbox_create_site` / `netbox_update_site` / `netbox_delete_site` | Manage sites |
| `netbox_create_tenant` / `netbox_update_tenant` / `netbox_delete_tenant` | Manage tenants |
| `netbox_create_tenant_group` / `netbox_update_tenant_group` / `netbox_delete_tenant_group` | Manage tenant groups |
| `netbox_create_tag` / `netbox_update_tag` / `netbox_delete_tag` | Manage tags |
| `netbox_create_vlan` / `netbox_update_vlan` / `netbox_delete_vlan` | Manage VLANs |
| `netbox_create_vlan_group` / `netbox_update_vlan_group` / `netbox_delete_vlan_group` | Manage VLAN groups |

#### IPAM Objects

| Tool | Description |
|------|-------------|
| `netbox_create_vrf` / `netbox_update_vrf` / `netbox_delete_vrf` | Manage VRFs |
| `netbox_create_prefix` / `netbox_update_prefix` / `netbox_delete_prefix` | Manage IP prefixes |
| `netbox_create_ip_address` / `netbox_update_ip_address` / `netbox_delete_ip_address` | Manage IP addresses |
| `netbox_create_ip_range` / `netbox_update_ip_range` / `netbox_delete_ip_range` | Manage IP ranges |

#### DCIM Objects

| Tool | Description |
|------|-------------|
| `netbox_create_device` / `netbox_update_device` / `netbox_delete_device` | Manage devices |
| `netbox_create_interface` / `netbox_update_interface` / `netbox_delete_interface` | Manage interfaces |
| `netbox_create_device_type` / `netbox_update_device_type` / `netbox_delete_device_type` | Manage device types |
| `netbox_create_manufacturer` / `netbox_update_manufacturer` / `netbox_delete_manufacturer` | Manage manufacturers |
| `netbox_create_rack` / `netbox_update_rack` / `netbox_delete_rack` | Manage racks |
| `netbox_create_rack_role` | Create rack roles |
| `netbox_create_cable` / `netbox_delete_cable` | Manage cables |

#### Circuit Objects

| Tool | Description |
|------|-------------|
| `netbox_create_circuit` / `netbox_update_circuit` / `netbox_delete_circuit` | Manage circuits |
| `netbox_create_provider` / `netbox_update_provider` / `netbox_delete_provider` | Manage providers |
| `netbox_create_circuit_type` / `netbox_update_circuit_type` / `netbox_delete_circuit_type` | Manage circuit types |

#### Virtualization Objects

| Tool | Description |
|------|-------------|
| `netbox_create_virtual_machine` / `netbox_update_virtual_machine` / `netbox_delete_virtual_machine` | Manage virtual machines |
| `netbox_create_cluster` / `netbox_update_cluster` / `netbox_delete_cluster` | Manage clusters |

#### Additional Infrastructure

| Tool | Description |
|------|-------------|
| `netbox_create_region` / `netbox_update_region` / `netbox_delete_region` | Manage regions |
| `netbox_create_location` / `netbox_update_location` / `netbox_delete_location` | Manage locations |

#### Generic Tools

| Tool | Description |
|------|-------------|
| `netbox_create_object` | Generic create for any NetBox object type |
| `netbox_update_object` | Generic update for any NetBox object type |
| `netbox_delete_object` | Generic delete for any NetBox object type |

> Note: the set of supported object types is explicitly defined and limited to the core NetBox objects for now, and won't work with object types from plugins.

## Usage

1. Create an API token in NetBox with appropriate permissions:
   - **Read operations**: Read-only permissions are sufficient
   - **Write operations**: Full create, update, and delete permissions for the objects you want to manage

2. Install dependencies:

    ```bash
    # Using UV (recommended)
    uv sync

    # Or using pip
    pip install -e .
    ```

3. Verify the server can run: `NETBOX_URL=https://netbox.example.com/ NETBOX_TOKEN=<your-api-token> uv run netbox-mcp-server`

4. Add the MCP server to your LLM client. See below for some examples with Claude.

### Claude Code

#### Stdio Transport (Default)

Add the server using the `claude mcp add` command:

```bash
claude mcp add --transport stdio netbox \
  --env NETBOX_URL=https://netbox.example.com/ \
  --env NETBOX_TOKEN=<your-api-token> \
  -- uv --directory /path/to/netbox-mcp-server run netbox-mcp-server
```

**Important notes:**

- Replace `/path/to/netbox-mcp-server` with the absolute path to your local clone
- The `--` separator distinguishes Claude Code flags from the server command
- Use `--scope project` to share the configuration via `.mcp.json` in version control
- Use `--scope user` to make it available across all your projects (default is `local`)

After adding, verify with `/mcp` in Claude Code or `claude mcp list` in your terminal.

#### HTTP Transport

For HTTP transport, first start the server manually:

```bash
# Start the server with HTTP transport (using .env or environment variables)
NETBOX_URL=https://netbox.example.com/ \
NETBOX_TOKEN=<your-api-token> \
TRANSPORT=http \
uv run netbox-mcp-server
```

Then add the running server to Claude Code:

```bash
# Add the HTTP MCP server (note: URL must include http:// or https:// prefix)
claude mcp add --transport http netbox http://127.0.0.1:8000/mcp
```

**Important notes:**

- The URL **must** include the protocol prefix (`http://` or `https://`)
- The default endpoint is `/mcp` when using HTTP transport
- The server must be running before Claude Code can connect
- Verify the connection with `claude mcp list` - you should see a ✓ next to the server name

### Claude Desktop

Add the server configuration to your Claude Desktop config file. On Mac, edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
    "mcpServers": {
        "netbox": {
            "command": "uv",
            "args": [
                "--directory",
                "/path/to/netbox-mcp-server",
                "run",
                "netbox-mcp-server"
            ],
            "env": {
                "NETBOX_URL": "https://netbox.example.com/",
                "NETBOX_TOKEN": "<your-api-token>"
            }
        }
    }
}
```

> On Windows, use full, escaped path to your instance, such as `C:\\Users\\myuser\\.local\\bin\\uv` and `C:\\Users\\myuser\\netbox-mcp-server`.
> For detailed troubleshooting, consult the [MCP quickstart](https://modelcontextprotocol.io/quickstart/user).

5. Use the tools in your LLM client.  For example:

**Read Operations:**
```text
> Get all devices in the 'Equinix DC14' site
...
> Tell me about my IPAM utilization
...
> What Cisco devices are in my network?
...
> Who made changes to the NYC site in the last week?
...
> Show me all configuration changes to the core router in the last month
```

**Write Operations:**
```text
> Create a new site called "San Francisco DC" with slug "sf-dc"
...
> Add a VLAN with ID 100 named "VLAN-100" for the NYC site
...
> Create a tenant named "Acme Corp" with slug "acme-corp"
...
> Update the status of site ID 5 to "planned"
...
> Delete VLAN with ID 42
...
> Create a tag named "production" with color "00ff00"
```

### Field Filtering (Token Optimization)

Both `netbox_get_objects()` and `netbox_get_object_by_id()` support an optional `fields` parameter to reduce token usage:

```python
# Without fields: ~5000 tokens for 50 devices
devices = netbox_get_objects('devices', {'site': 'datacenter-1'})

# With fields: ~500 tokens (90% reduction)
devices = netbox_get_objects(
    'devices',
    {'site': 'datacenter-1'},
    fields=['id', 'name', 'status', 'site']
)
```

**Common field patterns:**

- **Devices:** `['id', 'name', 'status', 'device_type', 'site', 'primary_ip4']`
- **IP Addresses:** `['id', 'address', 'status', 'dns_name', 'description']`
- **Interfaces:** `['id', 'name', 'type', 'enabled', 'device']`
- **Sites:** `['id', 'name', 'status', 'region', 'description']`

The `fields` parameter uses NetBox's native field filtering. See the [NetBox API documentation](https://docs.netbox.dev/en/stable/integrations/rest-api/) for details.

## Configuration

The server supports multiple configuration sources with the following precedence (highest to lowest):

1. **Command-line arguments** (highest priority)
2. **Environment variables**
3. **`.env` file** in the project root
4. **Default values** (lowest priority)

### Configuration Reference

| Setting | Type | Default | Required | Description |
|---------|------|---------|----------|-------------|
| `NETBOX_URL` | URL | - | Yes | Base URL of your NetBox instance (e.g., https://netbox.example.com/) |
| `NETBOX_TOKEN` | String | - | Yes | API token for authentication |
| `TRANSPORT` | `stdio` \| `http` | `stdio` | No | MCP transport protocol |
| `HOST` | String | `127.0.0.1` | If HTTP | Host address for HTTP server |
| `PORT` | Integer | `8000` | If HTTP | Port for HTTP server |
| `VERIFY_SSL` | Boolean | `true` | No | Whether to verify SSL certificates |
| `LOG_LEVEL` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` \| `CRITICAL` | `INFO` | No | Logging verbosity |

### Transport Examples

#### Stdio Transport (Claude Desktop/Code)

For local Claude Desktop or Claude Code usage with stdio transport:

```json
{
    "mcpServers": {
        "netbox": {
            "command": "uv",
            "args": ["--directory", "/path/to/netbox-mcp-server", "run", "netbox-mcp-server"],
            "env": {
                "NETBOX_URL": "https://netbox.example.com/",
                "NETBOX_TOKEN": "<your-api-token>"
            }
        }
    }
}
```

#### HTTP Transport (Web Clients)

For web-based MCP clients using HTTP/SSE transport:

```bash
# Using environment variables
export NETBOX_URL=https://netbox.example.com/
export NETBOX_TOKEN=<your-api-token>
export TRANSPORT=http
export HOST=127.0.0.1
export PORT=8000

uv run netbox-mcp-server

# Or using CLI arguments
uv run netbox-mcp-server \
  --netbox-url https://netbox.example.com/ \
  --netbox-token <your-api-token> \
  --transport http \
  --host 127.0.0.1 \
  --port 8000
```

### Example .env File

Create a `.env` file in the project root:

```env
# Core NetBox Configuration
NETBOX_URL=https://netbox.example.com/
NETBOX_TOKEN=your_api_token_here

# Transport Configuration (optional, defaults to stdio)
TRANSPORT=stdio

# HTTP Transport Settings (only used if TRANSPORT=http)
# HOST=127.0.0.1
# PORT=8000

# Security (optional, defaults to true)
VERIFY_SSL=true

# Logging (optional, defaults to INFO)
LOG_LEVEL=INFO
```

### CLI Arguments

All configuration options can be overridden via CLI arguments:

```bash
uv run netbox-mcp-server --help

# Common examples:
uv run netbox-mcp-server --log-level DEBUG --no-verify-ssl  # Development
uv run netbox-mcp-server --transport http --port 9000       # Custom HTTP port
```

## Docker Usage

### Standard Docker Image

Build and run the NetBox MCP server in a container:

```bash
# Build the image
docker build -t netbox-mcp-server:latest .

# Run with HTTP transport (required for Docker containers)
docker run --rm \
  -e NETBOX_URL=https://netbox.example.com/ \
  -e NETBOX_TOKEN=<your-api-token> \
  -e TRANSPORT=http \
  -e HOST=0.0.0.0 \
  -e PORT=8000 \
  -p 8000:8000 \
  netbox-mcp-server:latest
```

> **Note:** Docker containers require `TRANSPORT=http` since stdio transport doesn't work in containerized environments.

**Connecting to NetBox on your host machine:**

If your NetBox instance is running on your host machine (not in a container), you need to use `host.docker.internal` instead of `localhost` on macOS and Windows:

```bash
# For NetBox running on host (macOS/Windows)
docker run --rm \
  -e NETBOX_URL=http://host.docker.internal:18000/ \
  -e NETBOX_TOKEN=<your-api-token> \
  -e TRANSPORT=http \
  -e HOST=0.0.0.0 \
  -e PORT=8000 \
  -p 8000:8000 \
  netbox-mcp-server:latest
```

> **Note:** On Linux, you can use `--network host` instead, or use the host's IP address directly.

**With additional configuration options:**

```bash
docker run --rm \
  -e NETBOX_URL=https://netbox.example.com/ \
  -e NETBOX_TOKEN=<your-api-token> \
  -e TRANSPORT=http \
  -e HOST=0.0.0.0 \
  -e LOG_LEVEL=DEBUG \
  -e VERIFY_SSL=false \
  -p 8000:8000 \
  netbox-mcp-server:latest
```

The server will be accessible at `http://localhost:8000/mcp` for MCP clients. You can connect to it using your preferred method.

### Docker Compose

For easier deployment and management, use Docker Compose. Create a `docker-compose.yml` file:

```yaml
version: '3.8'

services:
  netbox-mcp-server:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: netbox-mcp-server
    environment:
      # Required: NetBox connection settings
      - NETBOX_URL=https://netbox.example.com/
      - NETBOX_TOKEN=your_api_token_here
      
      # Transport configuration (HTTP required for Docker)
      - TRANSPORT=http
      - HOST=0.0.0.0
      - PORT=8000
      
      # Optional: Security and logging
      - VERIFY_SSL=true
      - LOG_LEVEL=INFO
    ports:
      - "8000:8000"
    restart: unless-stopped
```

**Deploy with Docker Compose:**

```bash
# Start the service
docker-compose up -d

# View logs
docker-compose logs -f

# Stop the service
docker-compose down
```

**Important Notes:**
- Update `NETBOX_URL` and `NETBOX_TOKEN` in the `docker-compose.yml` file before starting
- No `.env` file is required - all configuration is in the compose file
- The service will be accessible at `http://localhost:8000/mcp` for MCP clients
- For production, consider using environment variable substitution or secrets management

## Write Operations Examples

### Creating Objects

**Create a Site:**
```python
netbox_create_site(
    name="New York Data Center",
    slug="nyc-dc",
    status="active",
    region=1,  # Optional: region ID
    tenant=2  # Optional: tenant ID
)
```

**Create a VLAN:**
```python
netbox_create_vlan(
    name="VLAN-100",
    vid=100,
    status="active",
    site=1,  # Optional: site ID
    tenant=2  # Optional: tenant ID
)
```

**Create a Tenant:**
```python
netbox_create_tenant(
    name="Acme Corporation",
    slug="acme-corp",
    group=1  # Optional: tenant group ID
)
```

**Create a Tag:**
```python
netbox_create_tag(
    name="production",
    slug="production",
    color="00ff00"  # Optional: hex color
)
```

### Updating Objects

**Update a Site:**
```python
netbox_update_site(
    site_id=1,
    status="planned",
    description="Site is being planned for Q2 2024"
)
```

**Update a VLAN:**
```python
netbox_update_vlan(
    vlan_id=5,
    name="VLAN-200-Updated",
    vid=200
)
```

### Deleting Objects

**Delete a Site:**
```python
netbox_delete_site(site_id=1)
```

**Delete a VLAN:**
```python
netbox_delete_vlan(vlan_id=5)
```

### Using Generic Tools

For objects that don't have specific tools, use the generic tools:

```python
# Create any object type
netbox_create_object(
    object_type="dcim.site",
    data={
        "name": "Chicago DC",
        "slug": "chi-dc",
        "status": "active"
    }
)

# Update any object type
netbox_update_object(
    object_type="ipam.vlan",
    object_id=10,
    data={"status": "deprecated"}
)

# Delete any object type
netbox_delete_object(
    object_type="dcim.site",
    object_id=3
)
```

## Development

Contributions are welcome!  Please open an issue or submit a PR.

## License

This project is licensed under the Apache 2.0 license.  See the LICENSE file for details.