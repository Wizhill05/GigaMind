"""Authenticated, stateless MCP Streamable HTTP transport."""

import asyncio
import contextvars

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import Tool

from gigamind.security import get_actor
from gigamind.services import context, trust
from gigamind.services.trust_schema import Proposal
from gigamind.services.memory import get_profile_rules

actor_context = contextvars.ContextVar("mcp_actor")
server = Server("GigaMind")


def create_manager():
    return StreamableHTTPSessionManager(server, stateless=True, json_response=True)


def schema(properties=None, required=None):
    return {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
        "additionalProperties": False,
    }


@server.list_tools()
async def list_tools():
    query = {"type": "string", "minLength": 1, "maxLength": 1000, "pattern": r"\S"}
    project = {"type": "string"}
    result = lambda key, typ: schema(
        {
            key: {
                "type": typ,
                **({"items": {"type": "object"}} if typ == "array" else {}),
            }
        },
        [key],
    )
    return [
        Tool(
            name="get_user_profile",
            description="Get profile rules (admin only).",
            inputSchema=schema(),
            outputSchema=result("rules", "array"),
        ),
        Tool(
            name="get_server_status",
            description="Get server status (admin only).",
            inputSchema=schema(),
            outputSchema=result("status", "string"),
        ),
        Tool(
            name="search_memory",
            description="Lexically search accepted knowledge.",
            inputSchema=schema(
                {
                    "query": query,
                    "project_id": project,
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                ["query"],
            ),
            outputSchema=result("results", "array"),
        ),
        Tool(
            name="get_memory",
            description="Get a knowledge record by ID.",
            inputSchema=schema({"memory_id": {"type": "string"}}, ["memory_id"]),
            outputSchema=result("memory", "object"),
        ),
        Tool(
            name="get_context",
            description="Get budgeted lexical context.",
            inputSchema=schema(
                {
                    "query": query,
                    "project_id": project,
                    "token_budget": {
                        "type": "integer",
                        "minimum": 64,
                        "maximum": 100000,
                    },
                },
                ["query"],
            ),
            outputSchema=schema(
                {
                    "rules": {"type": "array", "items": {"type": "object"}},
                    "memories": {"type": "array", "items": {"type": "object"}},
                    "citations": {"type": "array", "items": {"type": "object"}},
                    "handoff": {},
                },
                ["rules", "memories", "citations", "handoff"],
            ),
        ),
        Tool(
            name="propose_memory",
            description="Propose evidence-backed knowledge for review.",
            inputSchema=Proposal.model_json_schema(),
            outputSchema=result("proposal", "object"),
        ),
    ]


@server.call_tool()
async def call_tool(name, arguments):
    actor = actor_context.get()
    if name in ("get_server_status", "get_user_profile"):
        if not actor.is_admin:
            raise ValueError("403: Administrator required")
        if name == "get_server_status":
            return {"status": "online"}
        return {"rules": await asyncio.to_thread(get_profile_rules)}
    try:
        if name == "get_memory":
            return await asyncio.to_thread(
                context.get_memory, actor, arguments["memory_id"]
            )
        if name == "get_context":
            return await asyncio.to_thread(context.get_context, actor, **arguments)
        if name == "propose_memory":
            return await asyncio.to_thread(trust.create_proposal, actor, **arguments)
        if name == "search_memory":
            rows = await asyncio.to_thread(context.search_accepted, actor, **arguments)
            return {"results": rows}
    except HTTPException as exc:
        raise ValueError(f"{exc.status_code}: {exc.detail}") from exc
    raise ValueError("Unknown tool")


async def mcp_endpoint(scope, receive, send):
    request = Request(scope, receive)
    try:
        actor = await asyncio.to_thread(get_actor, request.headers.get("authorization"))
    except HTTPException as exc:
        await JSONResponse(
            {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
        )(scope, receive, send)
        return
    manager = scope.get("state", {}).get("mcp_manager")
    if manager is None:
        await JSONResponse({"detail": "MCP transport is not running"}, status_code=503)(
            scope, receive, send
        )
        return
    token = actor_context.set(actor)
    try:
        await manager.handle_request(scope, receive, send)
    finally:
        actor_context.reset(token)
