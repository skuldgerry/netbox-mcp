"""Start one disposable container with no network or real credentials."""

import subprocess
import sys
import uuid
from pathlib import Path


def main():
    image = sys.argv[1]
    name = "netbox-smoke-" + uuid.uuid4().hex[:12]
    try:
        subprocess.run(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                name,
                "--network",
                "none",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--env",
                "NETBOX_URL=http://127.0.0.1:18081",
                "--env",
                "NETBOX_TOKEN=smoke-netbox-token",
                "--env",
                "MCP_AUTH_TOKEN=smoke-mcp-token",
                "--env",
                "TRANSPORT=http",
                "--env",
                "HOST=127.0.0.1",
                "--env",
                "ENABLE_PLUGIN_DISCOVERY=false",
                image,
            ],
            check=True,
            timeout=90,
        )
        script = Path(__file__).with_name("container_probe.py").read_text(encoding="utf-8")
        subprocess.run(
            ["docker", "exec", "-i", name, "python", "-"],
            input=script,
            text=True,
            check=True,
            timeout=90,
        )
    finally:
        subprocess.run(["docker", "logs", name], check=False, timeout=15)
        subprocess.run(["docker", "rm", "--force", name], check=False, timeout=15)


if __name__ == "__main__":
    main()
