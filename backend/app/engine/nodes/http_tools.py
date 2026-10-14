"""HTTP tools for the AI agent node."""

from typing import Any

from app.engine.net import safe_request
from app.engine.nodes.base import NodeContext, NodeExecutionError
from app.engine.nodes.integrations import auth_headers

HTTP_CREDENTIAL_TYPES = ("http_header", "bearer_token")


def tool_definitions(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": {
                    "type": "object",
                    "description": (
                        "Sent as query parameters"
                        if tool["method"] == "GET"
                        else "Sent as JSON body"
                    ),
                    "additionalProperties": True,
                },
            },
        }
        for tool in tools
    ]


async def call_http_tool(
    ctx: NodeContext, tool: dict[str, Any], arguments: dict[str, Any]
) -> dict[str, Any]:
    headers: dict[str, str] = {}
    if tool.get("credential_id"):
        credential = await ctx.resolve_credential(tool["credential_id"], HTTP_CREDENTIAL_TYPES)
        headers.update(auth_headers(credential))
    try:
        result = await safe_request(
            ctx.http,
            tool["method"],
            tool["url"],
            headers=headers,
            params=arguments if tool["method"] == "GET" else None,
            json_body=arguments if tool["method"] != "GET" else None,
        )
    except NodeExecutionError as exc:
        return {"error": str(exc)}
    return {"status": result.status, "body": result.body}
