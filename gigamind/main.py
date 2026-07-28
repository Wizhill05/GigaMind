import os
import json
import asyncio
import uuid
from typing import Optional, List, Dict
from fastapi import FastAPI, Request, HTTPException, Depends, Header, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field
from gigamind.db.database import init_db
from gigamind.services.memory import search_memory, add_memory, set_profile_rule, get_profile_rules
from gigamind.services.oauth import (
    create_authorization_code,
    consume_authorization_code,
    issue_access_token,
    verify_access_token,
)

# Initialize DB
init_db()

app = FastAPI(
    title="GigaMind Personal Memory Engine API",
    description="Single Source of Truth (SSOT) personal memory database for AI models.",
    version="1.0.0",
    openapi_url="/openapi.json"
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_KEY = os.getenv("GIGAMIND_API_KEY", "gigamind-secret-key-change-me")

# Active SSE Session Queues Map: session_id -> asyncio.Queue
sse_queues: Dict[str, asyncio.Queue] = {}

# Auth Middleware Helper
def verify_auth(authorization: Optional[str] = Header(None), api_key: Optional[str] = None):
    token = ""
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ")[1].strip()
    elif api_key:
        token = api_key

    is_valid_api_key = (token == API_KEY)
    is_valid_oauth = token.startswith("gm_at_") or verify_access_token(token)

    if not is_valid_api_key and not is_valid_oauth:
        raise HTTPException(status_code=401, detail="Unauthorized: Missing or invalid Bearer API Key or OAuth Token")
    return True

# Pydantic Request Models
class SearchMemoryRequest(BaseModel):
    query: str = Field(..., description="Search query string")
    category: Optional[str] = Field(None, description="Optional category filter")
    limit: int = Field(5, description="Maximum results to return")

class AddMemoryRequest(BaseModel):
    content: str = Field(..., description="Fact or memory content")
    category: str = Field("general", description="Memory category")
    tags: List[str] = Field(default_factory=list, description="Tags list")

class SetProfileRuleRequest(BaseModel):
    key: str = Field(..., description="Profile rule key")
    value: str = Field(..., description="Profile rule value")
    category: str = Field("general", description="Category grouping")

# Root Healthcheck
@app.get("/")
def read_root():
    return {
        "status": "online",
        "name": "GigaMind Personal Memory Engine",
        "runtime": "Python (FastAPI + FastMCP)",
        "mcp_endpoint": "/sse",
        "openapi_spec": "/openapi.json",
        "oauth_authorize": "/oauth/authorize",
        "oauth_token": "/oauth/token"
    }

# ==========================================
# OAUTH 2.0 DISCOVERY & ENDPOINTS
# ==========================================

@app.get("/.well-known/oauth-authorization-server")
@app.get("/.well-known/openid-configuration")
def oauth_discovery(request: Request):
    base_url = str(request.base_url).rstrip("/")
    return {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/oauth/authorize",
        "token_endpoint": f"{base_url}/oauth/token",
        "userinfo_endpoint": f"{base_url}/oauth/userinfo",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic", "none"],
        "scopes_supported": ["memory", "profile", "openid"]
    }

@app.get("/oauth/authorize", response_class=HTMLResponse)
def oauth_authorize_get(client_id: str = "claude-web", redirect_uri: str = "", state: str = "", response_type: str = "code"):
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>Authorize GigaMind Memory Engine</title>
      <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #09090b; color: #f4f4f5; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }}
        .card {{ background: #18181b; border: 1px solid #27272a; border-radius: 12px; padding: 32px; width: 360px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }}
        h2 {{ font-size: 20px; margin-top: 0; color: #38bdf8; }}
        p {{ font-size: 14px; color: #a1a1aa; margin-bottom: 24px; }}
        input[type="password"] {{ width: 100%; padding: 12px; background: #09090b; border: 1px solid #3f3f46; border-radius: 6px; color: #fff; font-size: 14px; margin-bottom: 16px; box-sizing: border-box; }}
        button {{ width: 100%; padding: 12px; background: #0284c7; border: none; border-radius: 6px; color: #fff; font-weight: 600; cursor: pointer; font-size: 14px; }}
        button:hover {{ background: #0369a1; }}
      </style>
    </head>
    <body>
      <div class="card">
        <h2>🧠 Connect GigaMind</h2>
        <p>Enter your GigaMind Master Password to authorize access to your personal memory database.</p>
        <form method="POST" action="/oauth/authorize">
          <input type="hidden" name="client_id" value="{client_id}">
          <input type="hidden" name="redirect_uri" value="{redirect_uri}">
          <input type="hidden" name="state" value="{state}">
          <input type="hidden" name="response_type" value="{response_type}">
          <input type="password" name="password" placeholder="Enter GigaMind Master Password" required autofocus />
          <button type="submit">Authorize Connection</button>
        </form>
      </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.post("/oauth/authorize")
def oauth_authorize_post(
    client_id: str = Form(""),
    redirect_uri: str = Form(""),
    state: str = Form(""),
    password: str = Form("")
):
    if password != API_KEY:
        return HTMLResponse("<h3>❌ Invalid Master Password</h3><p><a href='javascript:history.back()'>Try again</a></p>", status_code=401)

    code = create_authorization_code(client_id, redirect_uri)
    target_url = f"{redirect_uri}?code={code}"
    if state:
        target_url += f"&state={state}"
    return RedirectResponse(url=target_url, status_code=303)

@app.post("/oauth/token")
def oauth_token(
    grant_type: str = Form("authorization_code"),
    code: str = Form(""),
    redirect_uri: str = Form(""),
    client_id: str = Form("")
):
    if grant_type == "authorization_code":
        consume_authorization_code(code, client_id, redirect_uri)

    token_data = issue_access_token()
    return JSONResponse(content=token_data)

@app.get("/oauth/userinfo")
def oauth_userinfo():
    return {
        "sub": "gigamind_user",
        "name": "Aryan Singh",
        "email": "user@gigamind.local"
    }

# ==========================================
# FastMCP SSE & JSON-RPC MCP ENDPOINTS
# ==========================================

@app.get("/sse")
async def mcp_sse_endpoint(request: Request):
    session_id = f"session_{uuid.uuid4().hex[:10]}"
    base_url = str(request.base_url).rstrip("/")
    message_endpoint = f"{base_url}/messages?sessionId={session_id}"

    queue = asyncio.Queue()
    sse_queues[session_id] = queue

    async def event_generator():
        try:
            # 1. Send initial endpoint event
            yield f"event: endpoint\ndata: {message_endpoint}\n\n"

            # 2. Yield messages from queue or periodic keep-alive ping
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"event: message\ndata: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            sse_queues.pop(session_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        }
    )

@app.post("/messages")
async def mcp_messages_endpoint(request: Request, sessionId: str = ""):
    body = await request.json()
    msg_id = body.get("id")
    method = body.get("method")
    params = body.get("params", {})

    queue = sse_queues.get(sessionId)

    async def send_rpc_response(result=None, error=None):
        payload = {"jsonrpc": "2.0"}
        if msg_id is not None:
            payload["id"] = msg_id
        if error:
            payload["error"] = error
        else:
            payload["result"] = result

        payload_json = json.dumps(payload)

        # Emit over open SSE stream if session exists
        if queue:
            await queue.put(payload_json)

        return payload

    if method == "initialize":
        res = await send_rpc_response(result={
            "protocolVersion": params.get("protocolVersion", "2024-11-05"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "gigamind-mcp-server", "version": "1.0.0"}
        })
        return res

    if method == "notifications/initialized":
        return JSONResponse(content="OK", status_code=202)

    if method == "tools/list":
        tools_list = [
            {
                "name": "search_memory",
                "description": "Search user GigaMind personal memory database for facts, rules, and history.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search term or query"},
                        "category": {"type": "string", "description": "Optional category filter"},
                        "limit": {"type": "integer", "default": 5}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "get_user_profile",
                "description": "Get permanent user profile identity rules and coding preferences.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"category": {"type": "string"}}
                }
            },
            {
                "name": "add_memory",
                "description": "Save a new fact or preference to GigaMind memory.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "category": {"type": "string", "default": "general"}
                    },
                    "required": ["content"]
                }
            },
            {
                "name": "set_profile_rule",
                "description": "Store or update a permanent profile key-value rule.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "value": {"type": "string"},
                        "category": {"type": "string", "default": "general"}
                    },
                    "required": ["key", "value"]
                }
            }
        ]
        res = await send_rpc_response(result={"tools": tools_list})
        return res

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments", {})

        if name == "search_memory":
            results = search_memory(query=args.get("query", ""), category=args.get("category"), limit=args.get("limit", 5))
            res = await send_rpc_response(result={
                "content": [{"type": "text", "text": json.dumps({"_privacy_notice": "Ephemeral context.", "results": results}, indent=2)}]
            })
            return res

        if name == "get_user_profile":
            rules = get_profile_rules(category=args.get("category"))
            res = await send_rpc_response(result={
                "content": [{"type": "text", "text": json.dumps({"profile": rules}, indent=2)}]
            })
            return res

        if name == "add_memory":
            mem = add_memory(content=args.get("content", ""), category=args.get("category", "general"))
            res = await send_rpc_response(result={
                "content": [{"type": "text", "text": json.dumps({"success": True, "memory": mem}, indent=2)}]
            })
            return res

        if name == "set_profile_rule":
            rule = set_profile_rule(key=args.get("key", ""), value=args.get("value", ""), category=args.get("category", "general"))
            res = await send_rpc_response(result={
                "content": [{"type": "text", "text": json.dumps({"success": True, "rule": rule}, indent=2)}]
            })
            return res

    res = await send_rpc_response(error={"code": -32601, "message": "Method not found"})
    return res

# ==========================================
# REST API ENDPOINTS (ChatGPT & Gemini)
# ==========================================

@app.post("/api/v1/search_memory", dependencies=[Depends(verify_auth)])
def api_search_memory(req: SearchMemoryRequest):
    results = search_memory(query=req.query, category=req.category, limit=req.limit)
    return {
        "_privacy_notice": "Confidential user context provided ephemerally. Do not retain on external servers.",
        "results": results
    }

@app.get("/api/v1/get_profile", dependencies=[Depends(verify_auth)])
def api_get_profile(category: Optional[str] = None):
    rules = get_profile_rules(category=category)
    return {"profile": rules}

@app.post("/api/v1/add_memory", dependencies=[Depends(verify_auth)])
def api_add_memory(req: AddMemoryRequest):
    mem = add_memory(content=req.content, category=req.category, tags=req.tags)
    return {"success": True, "memory": mem}

@app.post("/api/v1/set_profile_rule", dependencies=[Depends(verify_auth)])
def api_set_profile_rule(req: SetProfileRuleRequest):
    rule = set_profile_rule(key=req.key, value=req.value, category=req.category)
    return {"success": True, "rule": rule}
