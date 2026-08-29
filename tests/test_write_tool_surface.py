"""Guards against silently dropping the fork's write-tool surface."""

import ast
import inspect
from pathlib import Path

import netbox_mcp_server.server as server


def test_all_named_mutation_functions_are_mcp_tools() -> None:
    server_path = Path(__file__).parents[1] / "src" / "netbox_mcp_server" / "server.py"
    tree = ast.parse(server_path.read_text(encoding="utf-8"))
    mutation_functions = []

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith(("netbox_create_", "netbox_update_", "netbox_delete_")):
            continue
        mutation_functions.append(node)
        assert any(
            isinstance(decorator, ast.Attribute)
            and isinstance(decorator.value, ast.Name)
            and decorator.value.id == "mcp"
            and decorator.attr == "tool"
            for decorator in node.decorator_list
        ), f"{node.name} is no longer registered with FastMCP"

    assert len(mutation_functions) >= 70


class RecordingNetBoxClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []

    def create(self, endpoint: str, data: dict) -> dict:
        self.calls.append(("create", endpoint, data))
        return {"id": 1, **data}

    def update(self, endpoint: str, object_id: int, data: dict) -> dict:
        self.calls.append(("update", endpoint, {"id": object_id, **data}))
        return {"id": object_id, **data}

    def delete(self, endpoint: str, object_id: int) -> bool:
        self.calls.append(("delete", endpoint, object_id))
        return True


def _required_value(parameter: inspect.Parameter) -> object:
    if parameter.name == "object_type":
        return "dcim.site"
    if parameter.name == "data":
        return {"description": "test"}
    if parameter.annotation is int or parameter.name.endswith(("_id", "_a_id", "_b_id")):
        return 1
    return "test"


def test_every_mutation_tool_dispatches_to_the_client() -> None:
    client = RecordingNetBoxClient()
    previous_client = server.netbox
    server.netbox = client
    try:
        mutation_tools = [
            function
            for name, function in vars(server).items()
            if inspect.isfunction(function)
            and name.startswith(("netbox_create_", "netbox_update_", "netbox_delete_"))
        ]
        for function in mutation_tools:
            kwargs = {
                name: _required_value(parameter)
                for name, parameter in inspect.signature(function).parameters.items()
                if parameter.default is inspect.Parameter.empty
            }
            function(**kwargs)
    finally:
        server.netbox = previous_client

    assert len(mutation_tools) == 72
    assert len(client.calls) == 72
    assert {method for method, _, _ in client.calls} == {"create", "update", "delete"}
    assert all(endpoint and not endpoint.endswith("/") for _, endpoint, _ in client.calls)
