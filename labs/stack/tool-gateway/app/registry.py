"""The registry: which MCP servers are behind this gateway, and what they publish.

A server is registered by address. The gateway connects to it as an MCP client, asks it for its
tools, and keeps the answer. That is the whole of federation, and it is why the tool descriptions
a learner writes in c-02 arrive at the model unchanged: the gateway transcribes, it does not
author. A gateway that rewrote descriptions would be quietly editing the thing the lab is about.

Tool names are kept exactly as the server publishes them. That is not free: a gateway that
federates several servers has to do something about two servers publishing the same name, and
the usual answer is to prefix with the server. Prefixing here would rename
`create_meter_check_work_order` to `curated-create-meter-check-work-order`, and every policy
rule, log line and acceptance check in four handouts is written on the unprefixed name. So a
second server publishing a name that is already taken is refused at registration instead, which
is a worse gateway and a better lab.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mcp import Client


@dataclass
class Server:
    name: str
    url: str
    tools: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"name": self.name, "url": self.url, "tools": [t["name"] for t in self.tools]}


class Registry:
    def __init__(self) -> None:
        self.servers: dict[str, Server] = {}

    async def register(self, name: str, url: str) -> Server:
        tools = await self._list_tools(url)
        taken = {
            tool["name"]: server.name
            for server in self.servers.values()
            if server.name != name
            for tool in server.tools
        }
        clash = sorted(set(taken) & {tool["name"] for tool in tools})
        if clash:
            raise ValueError(
                f"{', '.join(clash)} is already published by {taken[clash[0]]}. "
                "This gateway does not prefix tool names, so two servers cannot publish the "
                "same one. Deregister the other server first."
            )
        server = Server(name=name, url=url, tools=tools)
        self.servers[name] = server
        return server

    def deregister(self, name: str) -> bool:
        return self.servers.pop(name, None) is not None

    def tools(self) -> list[dict]:
        out: list[dict] = []
        for server in self.servers.values():
            for tool in server.tools:
                out.append({**tool, "server": server.name})
        return sorted(out, key=lambda t: t["name"])

    def find(self, name: str) -> tuple[Server, dict] | None:
        for server in self.servers.values():
            for tool in server.tools:
                if tool["name"] == name:
                    return server, tool
        return None

    async def call(self, server: Server, tool: str, arguments: dict) -> dict:
        async with Client(server.url, read_timeout_seconds=60) as client:
            result = await client.call_tool(tool, arguments)
        return _plain(result)

    @staticmethod
    async def _list_tools(url: str) -> list[dict]:
        async with Client(url, read_timeout_seconds=30) as client:
            listed = await client.list_tools()
        out = []
        for tool in listed.tools:
            out.append(
                {
                    "name": tool.name,
                    "title": getattr(tool, "title", None),
                    "description": tool.description or "",
                    # mcp 2.x renamed these to snake_case on the model. The wire format is
                    # still inputSchema, and so is the OpenAI tool shape the model gateway
                    # wants, so the gateway keeps the wire spelling in its own JSON.
                    "inputSchema": tool.input_schema,
                    "outputSchema": tool.output_schema,
                    "annotations": _plain(getattr(tool, "annotations", None)) or {},
                }
            )
        return out


def _plain(value: Any) -> Any:
    """Whatever the SDK returned, as JSON the log and the response can carry."""
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    return value
