"""Authenticated, stateless MCP Streamable HTTP transport."""
import asyncio
import contextvars

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import Tool

from gigamind.security import get_actor
from gigamind.services.memory import get_profile_rules, search_memory

actor_context = contextvars.ContextVar('mcp_actor')
server = Server('GigaMind')
manager = StreamableHTTPSessionManager(server, stateless=True, json_response=True)


def schema(properties=None, required=None):
    return {'type': 'object', 'properties': properties or {}, 'required': required or [], 'additionalProperties': False}


@server.list_tools()
async def list_tools():
    return [
        Tool(name='get_user_profile', description='Get profile rules (admin only).', inputSchema=schema(), outputSchema=schema({'rules': {'type': 'array', 'items': {'type': 'object'}}}, ['rules'])),
        Tool(name='search_memory', description='Search memories (admin only).', inputSchema=schema({'query': {'type': 'string', 'minLength': 1, 'maxLength': 1000, 'pattern': r'\S'}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100}}, ['query']), outputSchema=schema({'results': {'type': 'array', 'items': {'type': 'object'}}}, ['results'])),
        Tool(name='get_server_status', description='Get server status.', inputSchema=schema(), outputSchema=schema({'status': {'type': 'string'}}, ['status'])),
    ]


@server.call_tool()
async def call_tool(name, arguments):
    actor = actor_context.get()
    if name == 'get_server_status':
        if not actor.is_admin and 'memory:read' not in actor.scopes:
            raise ValueError('Insufficient scope')
        return {'status': 'online'}
    if name not in ('get_user_profile', 'search_memory'):
        raise ValueError('Unknown tool')
    if not actor.is_admin:
        raise ValueError('Insufficient scope')
    if name == 'get_user_profile':
        return {'rules': await asyncio.to_thread(get_profile_rules)}
    results = await asyncio.to_thread(search_memory, query=arguments['query'], limit=arguments.get('limit', 5), scope='memories')
    return {'results': results}


async def mcp_endpoint(scope, receive, send):
    request = Request(scope, receive)
    try:
        actor = await asyncio.to_thread(get_actor, request.headers.get('authorization'))
    except HTTPException as exc:
        await JSONResponse({'detail': exc.detail}, status_code=exc.status_code)(scope, receive, send)
        return
    token = actor_context.set(actor)
    try:
        await manager.handle_request(scope, receive, send)
    finally:
        actor_context.reset(token)
