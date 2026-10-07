#!/usr/bin/env python3
"""Point a generator at an OpenAPI document and get one MCP tool per operation.

This is the button expose-one-operation is about. It reads the work order API's own description and writes
`generated/server.py`: twenty-three tools, one per operation, each docstring copied from the
operation summary. It is not a straw man. It does what this class of tool does, and the three
things it cannot do are the three failures the lab diagnoses:

1. **A summary is not a description.** The document says what an operation is. Nothing in it says
   when not to use it, what it costs, or what happens next, because an API description has no
   place to say that and no reason to.
2. **Constraints do not survive the crossing.** A JSON Schema `enum`, `pattern` or `maxLength` has
   no equivalent in a Python type hint, so a generator that derives its schema from type hints
   emits `str` and the constraint is gone. `type` is the field this matters on: six values, one
   of which cuts off a customer's water.
3. **One operation is one tool.** `POST /work-orders` creates six different kinds of work order,
   so the catalogue offers one name for six actions, and a rule written on that name covers all
   six.

Regenerate with:

    python3 labs/expose-one-operation/generate.py

It reads `https://wom.aquaflux.internal/openapi.json` unless `--from` says otherwise, so a change
to the API is reflected by running it again rather than by editing the output.
"""

from __future__ import annotations

import argparse
import json
import keyword
import pathlib
import re
import sys
import urllib.request

DEFAULT_SOURCE = "https://wom.aquaflux.internal/openapi.json"

# JSON Schema type to Python type hint. Everything a hint cannot carry is dropped here, which is
# the whole of failure two above.
PRIMITIVES = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "array": "list",
    "object": "dict",
}


def snake(name: str) -> str:
    out = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    out = re.sub(r"[^a-z0-9]+", "_", out)
    out = re.sub(r"_+", "_", out).strip("_")
    return f"{out}_" if keyword.iskeyword(out) else out


def resolve(schema: dict, document: dict) -> dict:
    while "$ref" in schema:
        ref = schema["$ref"].removeprefix("#/").split("/")
        node: object = document
        for part in ref:
            node = node[part]  # type: ignore[index]
        schema = node  # type: ignore[assignment]
    return schema


def hint(schema: dict, document: dict) -> str:
    schema = resolve(schema, document)
    if "anyOf" in schema:
        inner = [s for s in schema["anyOf"] if s.get("type") != "null"]
        base = hint(inner[0], document) if inner else "str"
        return f"{base} | None"
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), "string")
    return PRIMITIVES.get(kind or "string", "str")


def parameters(operation: dict, document: dict) -> list[dict]:
    """Every argument the operation takes, flattened into one list.

    Path, query and header parameters, plus one level of the request body's properties. A
    generator has to flatten, because a tool call is a flat bag of arguments and a REST request
    is not.
    """
    out: list[dict] = []
    for parameter in operation.get("parameters", []):
        parameter = resolve(parameter, document)
        out.append(
            {
                "name": snake(parameter["name"]),
                "wire": parameter["name"],
                "where": parameter["in"],
                "hint": hint(parameter.get("schema", {}), document),
                "required": bool(parameter.get("required")),
            }
        )

    body = operation.get("requestBody")
    if body:
        body = resolve(body, document)
        schema = body.get("content", {}).get("application/json", {}).get("schema")
        if schema:
            schema = resolve(schema, document)
            required = set(schema.get("required", []))
            for field, sub in (schema.get("properties") or {}).items():
                out.append(
                    {
                        "name": snake(field),
                        "wire": field,
                        "where": "body",
                        "hint": hint(sub, document),
                        "required": field in required,
                    }
                )
    return out


def signature(params: list[dict]) -> str:
    required = [p for p in params if p["required"]]
    optional = [p for p in params if not p["required"]]
    parts = [f"{p['name']}: {p['hint'].removesuffix(' | None')}" for p in required]
    parts += [f"{p['name']}: {p['hint'] if '|' in p['hint'] else p['hint'] + ' | None'} = None"
              for p in optional]
    return ", ".join(parts)


def render_tool(method: str, path: str, operation: dict, document: dict) -> str:
    name = snake(operation["operationId"])
    params = parameters(operation, document)
    summary = (operation.get("summary") or operation["operationId"]).strip().rstrip(".")

    body = {p["name"]: p["wire"] for p in params if p["where"] == "body"}
    query = {p["name"]: p["wire"] for p in params if p["where"] == "query"}
    header = {p["name"]: p["wire"] for p in params if p["where"] == "header"}
    path_args = {p["name"]: p["wire"] for p in params if p["where"] == "path"}

    return f'''

@mcp.tool()
def {name}({signature(params)}) -> dict:
    """{summary}."""
    return call(
        "{method.upper()}",
        "{path}",
        path_params={json.dumps(path_args)},
        query={json.dumps(query)},
        body={json.dumps(body)},
        header={json.dumps(header)},
        values=locals(),
    )
'''


HEADER = '''"""The work order API as MCP tools, generated from its OpenAPI document.

DO NOT EDIT. Regenerate with `python3 labs/expose-one-operation/generate.py`.

Twenty-three operations in, twenty-three tools out, each docstring copied from the operation
summary in the document. This file is expose-one-operation's starting point and its deliberate failure: read it,
run it, and read the gateway log before you read anything else.
"""

from __future__ import annotations

from mcp.server import MCPServer

from wom import call

mcp = MCPServer("aquaflux-work-orders-generated")
'''

FOOTER = '''

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8851)
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="source", default=DEFAULT_SOURCE)
    parser.add_argument(
        "--out",
        default=str(pathlib.Path(__file__).parent / "generated" / "server.py"),
    )
    args = parser.parse_args()

    if args.source.startswith("http"):
        with urllib.request.urlopen(args.source, timeout=20) as response:
            document = json.load(response)
    else:
        document = json.loads(pathlib.Path(args.source).read_text())

    tools = []
    for path, methods in document["paths"].items():
        for method, operation in methods.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            tools.append(render_tool(method, path, operation, document))

    out = pathlib.Path(args.out)
    out.write_text(HEADER + "".join(tools) + FOOTER)
    print(f"{len(tools)} tools written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
