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
from gigamind.services.memory import (
    search_memory,
    add_memory,
    set_profile_rule,
    get_profile_rules,
    get_memories,
    delete_memory,
    update_memory,
    get_conversations,
    delete_profile_rule,
    get_stats,
)
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

class UpdateMemoryRequest(BaseModel):
    content: Optional[str] = Field(None, description="Fact or memory content")
    category: Optional[str] = Field(None, description="Memory category")
    tags: Optional[List[str]] = Field(None, description="Tags list")

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

@app.get("/api/v1/memories", dependencies=[Depends(verify_auth)])
def api_get_memories(page: int = 1, limit: int = 20, category: Optional[str] = None):
    return get_memories(page=page, limit=limit, category=category)

@app.delete("/api/v1/memories/{id}", dependencies=[Depends(verify_auth)])
def api_delete_memory(id: str):
    success = delete_memory(id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Memory '{id}' not found")
    return {"success": True, "id": id, "message": f"Memory {id} deleted successfully"}

@app.put("/api/v1/memories/{id}", dependencies=[Depends(verify_auth)])
def api_update_memory(id: str, req: UpdateMemoryRequest):
    updated = update_memory(memory_id=id, content=req.content, category=req.category, tags=req.tags)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Memory '{id}' not found")
    return {"success": True, "memory": updated}

@app.get("/api/v1/conversations", dependencies=[Depends(verify_auth)])
def api_get_conversations(page: int = 1, limit: int = 20, platform: Optional[str] = None):
    return get_conversations(page=page, limit=limit, platform=platform)

@app.delete("/api/v1/profile/{id}", dependencies=[Depends(verify_auth)])
def api_delete_profile_rule(id: str):
    success = delete_profile_rule(id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Profile rule '{id}' not found")
    return {"success": True, "id": id, "message": f"Profile rule {id} deleted successfully"}

@app.get("/api/v1/stats", dependencies=[Depends(verify_auth)])
def api_get_stats():
    return get_stats()

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_ui():
    html_content = """<!DOCTYPE html>
<html lang="en" class="h-full bg-[#09090b] text-[#f4f4f5]">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>[ GIGAMIND // TACTICAL DASHBOARD ]</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
  <style>
    body { font-family: 'Inter', sans-serif; background-color: #09090b; color: #f4f4f5; }
    .font-mono { font-family: 'JetBrains Mono', monospace; }
    * { border-radius: 0px !important; }
    .scanline {
      background: linear-gradient(to bottom, rgba(255,255,255,0), rgba(255,255,255,0) 50%, rgba(0, 0, 0, 0.3) 50%, rgba(0, 0, 0, 0.3));
      background-size: 100% 4px;
    }
  </style>
</head>
<body class="min-h-screen bg-[#09090b] text-[#f4f4f5] font-sans antialiased border-t-2 border-[#e61919]">
  <div class="max-w-7xl mx-auto p-4 md:p-6">

    <!-- HEADER -->
    <header class="border border-[#27272a] bg-[#18181b] p-4 mb-6 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
      <div>
        <div class="flex items-center space-x-3">
          <span class="bg-[#e61919] text-white px-2 py-0.5 font-mono text-xs font-bold uppercase tracking-wider">SYSTEM ACTIVE</span>
          <h1 class="text-xl font-extrabold tracking-tight uppercase font-mono text-[#f4f4f5]">GIGAMIND // TELEMETRY & CONTROL</h1>
        </div>
        <p class="text-xs font-mono text-[#a1a1aa] mt-1">SINGLE SOURCE OF TRUTH // PERSONAL MEMORY ENGINE v1.0.0</p>
      </div>
      <div class="flex items-center gap-2 font-mono text-xs">
        <span class="text-[#a1a1aa]">API KEY:</span>
        <input type="password" id="apiKeyInput" value="gigamind-secret-key-change-me" class="bg-[#09090b] border border-[#27272a] px-2 py-1 text-white font-mono text-xs focus:border-[#38bdf8] outline-none">
        <button onclick="fetchStats(); fetchMemories(); fetchProfileRules(); fetchConversations();" class="bg-[#27272a] hover:bg-[#3f3f46] text-white px-3 py-1 font-mono uppercase text-xs border border-[#3f3f46]">CONNECT</button>
      </div>
    </header>

    <!-- TELEMETRY STATS BANNER -->
    <div id="statsBanner" class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      <div class="bg-[#18181b] border border-[#27272a] p-4">
        <div class="text-xs font-mono text-[#a1a1aa] uppercase">[ STAT // MEMORIES ]</div>
        <div id="statMemories" class="text-2xl font-bold font-mono text-[#38bdf8] mt-1">--</div>
      </div>
      <div class="bg-[#18181b] border border-[#27272a] p-4">
        <div class="text-xs font-mono text-[#a1a1aa] uppercase">[ STAT // RULES ]</div>
        <div id="statRules" class="text-2xl font-bold font-mono text-[#38bdf8] mt-1">--</div>
      </div>
      <div class="bg-[#18181b] border border-[#27272a] p-4">
        <div class="text-xs font-mono text-[#a1a1aa] uppercase">[ STAT // CHAT LOGS ]</div>
        <div id="statLogs" class="text-2xl font-bold font-mono text-[#38bdf8] mt-1">--</div>
      </div>
      <div class="bg-[#18181b] border border-[#27272a] p-4">
        <div class="text-xs font-mono text-[#a1a1aa] uppercase">[ STAT // SESSIONS ]</div>
        <div id="statSessions" class="text-2xl font-bold font-mono text-[#38bdf8] mt-1">--</div>
      </div>
    </div>

    <!-- LIVE SEARCH BAR WITH SEMANTIC SCORE INDICATOR -->
    <section class="bg-[#18181b] border border-[#27272a] p-4 mb-6">
      <div class="flex flex-col md:flex-row gap-3">
        <div class="relative flex-1">
          <input type="text" id="searchInput" onkeyup="handleSearch(event)" placeholder="LIVE NATURAL LANGUAGE VECTOR SEARCH (Press ENTER or type query)..." class="w-full bg-[#09090b] border border-[#27272a] p-3 text-sm text-white font-mono placeholder-[#52525b] focus:border-[#38bdf8] outline-none">
        </div>
        <button onclick="executeSearch()" class="bg-[#38bdf8] hover:bg-[#0284c7] text-[#09090b] font-bold px-6 py-3 font-mono uppercase text-xs tracking-wider">
          SEARCH VECTOR DB
        </button>
      </div>
      <div id="searchResultsArea" class="mt-4 hidden space-y-2">
        <div class="text-xs font-mono text-[#a1a1aa] border-b border-[#27272a] pb-1 uppercase flex justify-between">
          <span>>>> VECTOR RELEVANCE RESULTS</span>
          <button onclick="document.getElementById('searchResultsArea').classList.add('hidden')" class="text-[#e61919] hover:underline">[CLEAR SEARCH]</button>
        </div>
        <div id="searchResultsList" class="space-y-2"></div>
      </div>
    </section>

    <!-- MAIN GRID: MEMORIES & PROFILE RULES -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">

      <!-- MEMORIES SECTION (2 cols) -->
      <section class="lg:col-span-2 bg-[#18181b] border border-[#27272a] p-4 flex flex-col">
        <div class="flex justify-between items-center border-b border-[#27272a] pb-3 mb-4">
          <h2 class="text-sm font-bold font-mono uppercase text-[#f4f4f5] tracking-wider flex items-center gap-2">
            <span class="w-2 h-2 bg-[#38bdf8]"></span> MEMORY REPOSITORY
          </h2>
          <div class="flex items-center gap-2">
            <select id="memoryCategoryFilter" onchange="fetchMemories()" class="bg-[#09090b] border border-[#27272a] text-xs font-mono text-white px-2 py-1 outline-none">
              <option value="">ALL CATEGORIES</option>
              <option value="general">GENERAL</option>
              <option value="coding">CODING</option>
              <option value="personal">PERSONAL</option>
              <option value="project">PROJECT</option>
            </select>
            <button onclick="openNewMemoryModal()" class="bg-[#27272a] hover:bg-[#3f3f46] text-white text-xs font-mono px-3 py-1 uppercase border border-[#3f3f46]">+ NEW MEMORY</button>
          </div>
        </div>

        <div id="memoriesList" class="space-y-3 flex-1 overflow-y-auto max-h-[500px] pr-1">
          <!-- Memory Cards inserted dynamically -->
        </div>

        <!-- Pagination -->
        <div class="flex justify-between items-center border-t border-[#27272a] pt-3 mt-4 text-xs font-mono text-[#a1a1aa]">
          <button onclick="prevMemoriesPage()" class="hover:text-white">[ &lt; PREV ]</button>
          <span id="memoriesPageInfo">PAGE 1 OF 1</span>
          <button onclick="nextMemoriesPage()" class="hover:text-white">[ NEXT &gt; ]</button>
        </div>
      </section>

      <!-- PROFILE RULES SECTION (1 col) -->
      <section class="bg-[#18181b] border border-[#27272a] p-4 flex flex-col">
        <div class="flex justify-between items-center border-b border-[#27272a] pb-3 mb-4">
          <h2 class="text-sm font-bold font-mono uppercase text-[#f4f4f5] tracking-wider flex items-center gap-2">
            <span class="w-2 h-2 bg-[#e61919]"></span> PROFILE RULES
          </h2>
          <button onclick="openNewRuleModal()" class="bg-[#27272a] hover:bg-[#3f3f46] text-white text-xs font-mono px-2 py-1 uppercase border border-[#3f3f46]">+ ADD RULE</button>
        </div>

        <div id="profileRulesList" class="space-y-3 flex-1 overflow-y-auto max-h-[500px]">
          <!-- Profile Rule Items inserted dynamically -->
        </div>
      </section>

    </div>

    <!-- CONVERSATION HISTORY SECTION -->
    <section class="bg-[#18181b] border border-[#27272a] p-4">
      <div class="flex justify-between items-center border-b border-[#27272a] pb-3 mb-4">
        <h2 class="text-sm font-bold font-mono uppercase text-[#f4f4f5] tracking-wider flex items-center gap-2">
          <span class="w-2 h-2 bg-[#a1a1aa]"></span> CHAT HISTORIES & TRANSCRIPTS
        </h2>
        <span class="text-xs font-mono text-[#a1a1aa]">PLATFORMS: CLAUDE WEB // CUSTOM GPT</span>
      </div>
      <div id="conversationsList" class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <!-- Conversation Cards inserted dynamically -->
      </div>
    </section>

  </div>

  <!-- INTERACTIVE EDIT MODAL -->
  <div id="editorModal" class="fixed inset-0 bg-black/80 flex items-center justify-center hidden p-4 z-50">
    <div class="bg-[#18181b] border-2 border-[#38bdf8] max-w-xl w-full p-6 shadow-2xl">
      <div class="flex justify-between items-center border-b border-[#27272a] pb-3 mb-4">
        <h3 id="modalTitle" class="text-sm font-bold font-mono uppercase text-[#38bdf8] tracking-wider">[ EDIT ITEM ]</h3>
        <button onclick="closeModal()" class="text-[#e61919] font-mono hover:underline font-bold text-xs">[ CLOSE X ]</button>
      </div>
      <div id="modalBody" class="space-y-4 font-mono text-xs">
        <!-- Dynamic Modal Input Controls -->
      </div>
      <div class="flex justify-end gap-3 border-t border-[#27272a] pt-4 mt-6">
        <button onclick="closeModal()" class="bg-[#27272a] hover:bg-[#3f3f46] text-white px-4 py-2 font-mono text-xs uppercase">CANCEL</button>
        <button id="modalSaveBtn" onclick="saveModalData()" class="bg-[#38bdf8] hover:bg-[#0284c7] text-[#09090b] font-bold px-6 py-2 font-mono text-xs uppercase">SAVE CHANGES</button>
      </div>
    </div>
  </div>

  <!-- JS LOGIC ARCHITECTURE -->
  <script>
    let currentMemoriesPage = 1;
    let totalMemoriesPages = 1;
    let editingItemType = null; // 'memory', 'rule', 'new_memory', 'new_rule'
    let editingItemId = null;

    function getAuthHeader() {
      const apiKey = document.getElementById('apiKeyInput').value;
      return { 'Authorization': 'Bearer ' + apiKey, 'Content-Type': 'application/json' };
    }

    async function fetchStats() {
      try {
        const res = await fetch('/api/v1/stats', { headers: getAuthHeader() });
        if (!res.ok) return;
        const data = await res.json();
        document.getElementById('statMemories').innerText = data.total_memories || 0;
        document.getElementById('statRules').innerText = data.total_profile_rules || 0;
        document.getElementById('statLogs').innerText = data.total_chat_logs || 0;
        document.getElementById('statSessions').innerText = data.total_task_sessions || 0;
      } catch (e) { console.error('Stats error:', e); }
    }

    async function fetchMemories() {
      try {
        const cat = document.getElementById('memoryCategoryFilter').value;
        const url = `/api/v1/memories?page=${currentMemoriesPage}&limit=6${cat ? '&category=' + cat : ''}`;
        const res = await fetch(url, { headers: getAuthHeader() });
        if (!res.ok) return;
        const data = await res.json();
        totalMemoriesPages = data.pages || 1;
        document.getElementById('memoriesPageInfo').innerText = `PAGE ${data.page} OF ${totalMemoriesPages}`;

        const container = document.getElementById('memoriesList');
        if (!data.memories || data.memories.length === 0) {
          container.innerHTML = '<div class="p-4 text-xs font-mono text-[#52525b] border border-[#27272a] text-center">NO MEMORY RECORDS FOUND</div>';
          return;
        }

        container.innerHTML = data.memories.map(mem => `
          <div class="bg-[#09090b] border border-[#27272a] p-3 hover:border-[#38bdf8] transition-colors">
            <div class="flex justify-between items-start mb-2">
              <div class="flex items-center gap-2">
                <span class="bg-[#27272a] text-[#38bdf8] px-1.5 py-0.5 text-[10px] font-mono uppercase">${mem.category}</span>
                <span class="text-[10px] font-mono text-[#52525b]">${mem.id}</span>
              </div>
              <div class="flex items-center gap-2">
                <button onclick="openEditMemoryModal('${mem.id}', \`${escapeHtml(mem.content)}\`, '${mem.category}', \`${escapeHtml(JSON.stringify(mem.tags))}\`)" class="text-xs font-mono text-[#38bdf8] hover:underline">[EDIT]</button>
                <button onclick="deleteMemory('${mem.id}')" class="text-xs font-mono text-[#e61919] hover:underline">[DEL]</button>
              </div>
            </div>
            <p class="text-xs text-[#f4f4f5] font-sans leading-relaxed mb-2">${escapeHtml(mem.content)}</p>
            <div class="flex justify-between items-center text-[10px] font-mono text-[#52525b]">
              <span>TAGS: ${mem.tags && mem.tags.length ? mem.tags.join(', ') : 'NONE'}</span>
              <span>${mem.created_at ? mem.created_at.split('T')[0] : ''}</span>
            </div>
          </div>
        `).join('');
      } catch (e) { console.error('Memories error:', e); }
    }

    async function fetchProfileRules() {
      try {
        const res = await fetch('/api/v1/get_profile', { headers: getAuthHeader() });
        if (!res.ok) return;
        const data = await res.json();
        const container = document.getElementById('profileRulesList');
        if (!data.profile || data.profile.length === 0) {
          container.innerHTML = '<div class="p-4 text-xs font-mono text-[#52525b] border border-[#27272a] text-center">NO PROFILE RULES DEFINED</div>';
          return;
        }
        container.innerHTML = data.profile.map(rule => `
          <div class="bg-[#09090b] border border-[#27272a] p-3">
            <div class="flex justify-between items-start mb-1">
              <span class="font-mono text-xs font-bold text-[#e61919] uppercase">${escapeHtml(rule.key)}</span>
              <button onclick="deleteProfileRule('${rule.id}')" class="text-[10px] font-mono text-[#e61919] hover:underline">[DEL]</button>
            </div>
            <p class="text-xs font-mono text-[#a1a1aa] break-all">${escapeHtml(rule.value)}</p>
          </div>
        `).join('');
      } catch (e) { console.error('Profile rules error:', e); }
    }

    async function fetchConversations() {
      try {
        const res = await fetch('/api/v1/conversations?limit=4', { headers: getAuthHeader() });
        if (!res.ok) return;
        const data = await res.json();
        const container = document.getElementById('conversationsList');
        if (!data.conversations || data.conversations.length === 0) {
          container.innerHTML = '<div class="p-4 text-xs font-mono text-[#52525b] border border-[#27272a] text-center col-span-2">NO CHAT TRANSCRIPT LOGS STORED</div>';
          return;
        }
        container.innerHTML = data.conversations.map(conv => `
          <div class="bg-[#09090b] border border-[#27272a] p-3">
            <div class="flex justify-between items-center mb-1">
              <span class="text-[10px] font-mono bg-[#27272a] text-white px-1.5 py-0.5 uppercase">${conv.platform}</span>
              <span class="text-[10px] font-mono text-[#52525b]">${conv.id}</span>
            </div>
            <h4 class="text-xs font-bold text-[#f4f4f5] font-sans mb-1">${escapeHtml(conv.title)}</h4>
            <p class="text-xs text-[#a1a1aa] font-sans line-clamp-2">${escapeHtml(conv.summary)}</p>
          </div>
        `).join('');
      } catch (e) { console.error('Conversations error:', e); }
    }

    function handleSearch(e) {
      if (e.key === 'Enter') executeSearch();
    }

    async function executeSearch() {
      const q = document.getElementById('searchInput').value.trim();
      if (!q) return;
      try {
        const res = await fetch('/api/v1/search_memory', {
          method: 'POST',
          headers: getAuthHeader(),
          body: JSON.stringify({ query: q, limit: 5 })
        });
        if (!res.ok) return;
        const data = await res.json();
        const container = document.getElementById('searchResultsList');
        document.getElementById('searchResultsArea').classList.remove('hidden');
        if (!data.results || data.results.length === 0) {
          container.innerHTML = '<div class="p-2 text-xs font-mono text-[#52525b]">NO SEMANTIC MATCHES FOUND ABOVE THRESHOLD</div>';
          return;
        }
        container.innerHTML = data.results.map(r => {
          const scorePct = (r.score * 100).toFixed(1);
          return `
            <div class="bg-[#09090b] border border-[#27272a] p-2 flex justify-between items-center gap-4">
              <div class="flex-1">
                <span class="text-[10px] font-mono text-[#38bdf8] uppercase mr-2">[${r.source.toUpperCase()}]</span>
                <span class="text-xs font-sans text-white">${escapeHtml(r.content)}</span>
              </div>
              <div class="bg-[#27272a] border border-[#38bdf8] px-2 py-1 font-mono text-xs text-[#38bdf8] font-bold">
                MATCH: ${scorePct}%
              </div>
            </div>
          `;
        }).join('');
      } catch (e) { console.error('Search error:', e); }
    }

    function prevMemoriesPage() {
      if (currentMemoriesPage > 1) { currentMemoriesPage--; fetchMemories(); }
    }
    function nextMemoriesPage() {
      if (currentMemoriesPage < totalMemoriesPages) { currentMemoriesPage++; fetchMemories(); }
    }

    // Delete handlers
    async function deleteMemory(id) {
      if (!confirm(`Confirm deletion of Memory ID: ${id}?`)) return;
      try {
        const res = await fetch(`/api/v1/memories/${id}`, { method: 'DELETE', headers: getAuthHeader() });
        if (res.ok) { fetchMemories(); fetchStats(); }
      } catch (e) { console.error(e); }
    }

    async function deleteProfileRule(id) {
      if (!confirm(`Confirm deletion of Profile Rule: ${id}?`)) return;
      try {
        const res = await fetch(`/api/v1/profile/${id}`, { method: 'DELETE', headers: getAuthHeader() });
        if (res.ok) { fetchProfileRules(); fetchStats(); }
      } catch (e) { console.error(e); }
    }

    // Modal handlers
    function openNewMemoryModal() {
      editingItemType = 'new_memory';
      document.getElementById('modalTitle').innerText = '[ CREATE NEW MEMORY RECORD ]';
      document.getElementById('modalBody').innerHTML = `
        <div>
          <label class="block text-[#a1a1aa] mb-1">CONTENT STATEMENT</label>
          <textarea id="modalContentInput" rows="3" class="w-full bg-[#09090b] border border-[#27272a] p-2 text-white outline-none focus:border-[#38bdf8]" placeholder="Enter factual content..."></textarea>
        </div>
        <div>
          <label class="block text-[#a1a1aa] mb-1">CATEGORY</label>
          <input type="text" id="modalCategoryInput" value="general" class="w-full bg-[#09090b] border border-[#27272a] p-2 text-white outline-none focus:border-[#38bdf8]">
        </div>
        <div>
          <label class="block text-[#a1a1aa] mb-1">TAGS (COMMA SEPARATED)</label>
          <input type="text" id="modalTagsInput" placeholder="python, api, config" class="w-full bg-[#09090b] border border-[#27272a] p-2 text-white outline-none focus:border-[#38bdf8]">
        </div>
      `;
      document.getElementById('editorModal').classList.remove('hidden');
    }

    function openEditMemoryModal(id, content, category, tagsJson) {
      editingItemType = 'memory';
      editingItemId = id;
      let tags = [];
      try { tags = JSON.parse(tagsJson); } catch (e) {}
      document.getElementById('modalTitle').innerText = `[ EDIT MEMORY // ${id} ]`;
      document.getElementById('modalBody').innerHTML = `
        <div>
          <label class="block text-[#a1a1aa] mb-1">CONTENT STATEMENT</label>
          <textarea id="modalContentInput" rows="3" class="w-full bg-[#09090b] border border-[#27272a] p-2 text-white outline-none focus:border-[#38bdf8]">${escapeHtml(content)}</textarea>
        </div>
        <div>
          <label class="block text-[#a1a1aa] mb-1">CATEGORY</label>
          <input type="text" id="modalCategoryInput" value="${escapeHtml(category)}" class="w-full bg-[#09090b] border border-[#27272a] p-2 text-white outline-none focus:border-[#38bdf8]">
        </div>
        <div>
          <label class="block text-[#a1a1aa] mb-1">TAGS (COMMA SEPARATED)</label>
          <input type="text" id="modalTagsInput" value="${tags.join(', ')}" class="w-full bg-[#09090b] border border-[#27272a] p-2 text-white outline-none focus:border-[#38bdf8]">
        </div>
      `;
      document.getElementById('editorModal').classList.remove('hidden');
    }

    function openNewRuleModal() {
      editingItemType = 'new_rule';
      document.getElementById('modalTitle').innerText = '[ DEFINE PROFILE RULE ]';
      document.getElementById('modalBody').innerHTML = `
        <div>
          <label class="block text-[#a1a1aa] mb-1">RULE KEY (UNIQUE)</label>
          <input type="text" id="modalRuleKey" class="w-full bg-[#09090b] border border-[#27272a] p-2 text-white outline-none focus:border-[#38bdf8]" placeholder="e.g. primary_programming_language">
        </div>
        <div>
          <label class="block text-[#a1a1aa] mb-1">RULE VALUE STATEMENT</label>
          <input type="text" id="modalRuleValue" class="w-full bg-[#09090b] border border-[#27272a] p-2 text-white outline-none focus:border-[#38bdf8]" placeholder="e.g. Python / TypeScript">
        </div>
      `;
      document.getElementById('editorModal').classList.remove('hidden');
    }

    function closeModal() {
      document.getElementById('editorModal').classList.add('hidden');
    }

    async function saveModalData() {
      if (editingItemType === 'new_memory') {
        const content = document.getElementById('modalContentInput').value.trim();
        const category = document.getElementById('modalCategoryInput').value.trim() || 'general';
        const tags = document.getElementById('modalTagsInput').value.split(',').map(t => t.trim()).filter(Boolean);
        if (!content) return;
        await fetch('/api/v1/add_memory', {
          method: 'POST',
          headers: getAuthHeader(),
          body: JSON.stringify({ content, category, tags })
        });
        fetchMemories(); fetchStats();
      } else if (editingItemType === 'memory') {
        const content = document.getElementById('modalContentInput').value.trim();
        const category = document.getElementById('modalCategoryInput').value.trim();
        const tags = document.getElementById('modalTagsInput').value.split(',').map(t => t.trim()).filter(Boolean);
        await fetch(`/api/v1/memories/${editingItemId}`, {
          method: 'PUT',
          headers: getAuthHeader(),
          body: JSON.stringify({ content, category, tags })
        });
        fetchMemories();
      } else if (editingItemType === 'new_rule') {
        const key = document.getElementById('modalRuleKey').value.trim();
        const value = document.getElementById('modalRuleValue').value.trim();
        if (!key || !value) return;
        await fetch('/api/v1/set_profile_rule', {
          method: 'POST',
          headers: getAuthHeader(),
          body: JSON.stringify({ key, value, category: 'general' })
        });
        fetchProfileRules(); fetchStats();
      }
      closeModal();
    }

    function escapeHtml(str) {
      if (!str) return '';
      return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
    }

    // Init fetch on load
    window.onload = function() {
      fetchStats();
      fetchMemories();
      fetchProfileRules();
      fetchConversations();
    };
  </script>
</body>
</html>
"""
    return HTMLResponse(content=html_content)

