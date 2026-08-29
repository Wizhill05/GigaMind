import os
import json
import asyncio
import uuid
import base64
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Request, HTTPException, Depends, Header, Form, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from gigamind.db.database import init_db
from gigamind.services.storage import storage_service
from gigamind.services.indexing import index_file_content, reindex_storage_file_by_key, list_indexed_storage_files, get_file_chunks, register_storage_file
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
    reset_all_memories,
    export_all_memories,
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

frontend_dist_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "dist")
assets_dir = os.path.join(frontend_dist_dir, "assets")
if os.path.exists(assets_dir):
    app.mount("/assets", StaticFiles(directory=assets_dir), name="static_assets")

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
    scope: str = Field("all", description="Search domain: 'all' | 'memories' | 'files'")
    category: Optional[str] = Field(None, description="Optional category filter")
    source_agent: Optional[str] = Field(None, description="Optional source agent filter (e.g. claude, gpt, gemini, user)")
    limit: int = Field(5, description="Maximum results to return")

class SearchFilesRequest(BaseModel):
    query: str = Field(..., description="Query to search inside uploaded documents")
    limit: int = Field(5, description="Maximum results to return")

class ReindexFileRequest(BaseModel):
    key: str = Field(..., description="R2 storage key to re-index")

class DeleteMemoryApiRequest(BaseModel):
    memory_id: str = Field(..., description="The exact ID of the memory item to delete (e.g. 'mem_123')")
    user_confirmed: bool = Field(True, description="Confirmation flag that user explicitly approved deletion")

class AddMemoryRequest(BaseModel):
    content: str = Field(..., description="Fact or memory content")
    category: str = Field("general", description="Memory category")
    source_agent: str = Field("user", description="Source agent or tool creating this memory (e.g. claude, gpt, gemini, user)")
    tags: List[str] = Field(default_factory=list, description="Tags list")
    attachments: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="R2 file attachment metadata list")
    file_keys: Optional[List[str]] = Field(default_factory=list, description="Existing R2 storage keys to link")
    media_url: Optional[str] = Field(None, description="Legacy media URL for backward compatibility")
    media_type: Optional[str] = Field(None, description="Legacy media MIME or file type")

class SetProfileRuleRequest(BaseModel):
    key: str = Field(..., description="Profile rule key")
    value: str = Field(..., description="Profile rule value")
    category: str = Field("general", description="Category grouping")
    source_agent: str = Field("user", description="Source agent or tool setting this rule (e.g. claude, gpt, gemini, user)")

class UpdateMemoryRequest(BaseModel):
    content: Optional[str] = Field(None, description="Fact or memory content")
    category: Optional[str] = Field(None, description="Memory category")
    source_agent: Optional[str] = Field(None, description="Source agent or tool (e.g. claude, gpt, gemini, user)")
    tags: Optional[List[str]] = Field(None, description="Tags list")
    attachments: Optional[List[Dict[str, Any]]] = Field(None, description="Updated attachments list")

class ResetMemoriesRequest(BaseModel):
    password: str = Field(..., description="Master API Key / Password to confirm hard memory purge")

class PresignedUrlRequest(BaseModel):
    key: str = Field(..., description="Cloudflare R2 storage key")
    expires_in: int = Field(3600, description="Expiration time in seconds (default 3600)")
    filename: Optional[str] = Field(None, description="Optional override filename for Content-Disposition")
    inline: bool = Field(True, description="Inline display (True) or force attachment download (False)")

class PresignedUploadUrlRequest(BaseModel):
    filename: str = Field(..., description="Target file name")
    content_type: str = Field("application/octet-stream", description="File MIME type")
    expires_in: int = Field(3600, description="Expiration time in seconds (default 3600)")

class FileUploadBase64Request(BaseModel):
    filename: str = Field(..., description="File name")
    content_base64: str = Field(..., description="Base64 encoded file content")
    mime_type: Optional[str] = Field(None, description="MIME content type")

def _format_search_results_for_agent(results: List[Dict[str, Any]], query: str, scope: str) -> str:
    if not results:
        return f"No matching results found in GigaMind for query: '{query}' (scope: {scope})."

    lines = [f"Found {len(results)} relevant item(s) for query: '{query}' (scope: {scope}):\n"]
    file_items = [r for r in results if r.get("source") == "file"]
    mem_items = [r for r in results if r.get("source") != "file"]

    if file_items:
        lines.append("### 📄 Matching Files & Document Excerpts:")
        for idx, f in enumerate(file_items, 1):
            citation = f.get("citation", f.get("filename", "File"))
            url = f.get("url")
            link_md = f" | [Download / Open]({url})" if url else ""
            lines.append(f"{idx}. **[{citation}]** (Score: {f.get('score', 0):.2f}){link_md}")
            lines.append(f"   > {f.get('content', '').strip()}\n")

    if mem_items:
        lines.append("### 🧠 Matching Memories & Facts:")
        for idx, m in enumerate(mem_items, 1):
            tags_str = f" [tags: {', '.join(m.get('tags', []))}]" if m.get("tags") else ""
            lines.append(f"{idx}. **Memory ({m.get('category', 'general')})** (Agent: {m.get('source_agent', 'user')}, Score: {m.get('score', 0):.2f}){tags_str}:")
            lines.append(f"   {m.get('content', '').strip()}")
            if m.get("attachments"):
                att_names = [a.get("filename", "file") for a in m.get("attachments", [])]
                lines.append(f"   📎 Attachments: {', '.join(att_names)}")
            lines.append("")

    return "\n".join(lines)
# Dashboard UI Helper
def dashboard_ui():
    index_file = os.path.join(frontend_dist_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return HTMLResponse(content="<h1>Dashboard Build Not Found</h1><p>Run `npm run build` inside frontend/ directory.</p>", status_code=404)

@app.get("/dashboard")
def get_dashboard():
    return dashboard_ui()

# Root Route (serves React Dashboard UI for web browsers, JSON for API clients)
@app.get("/")
def read_root(request: Request):
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return dashboard_ui()
    return {
        "status": "online",
        "name": "GigaMind Personal Memory Engine",
        "runtime": "Python (FastAPI + FastMCP)",
        "dashboard_ui": "/dashboard",
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
            yield f"event: endpoint\ndata: {message_endpoint}\n\n"
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

    if method == "tools/list":
        tools_list = [
            {
                "name": "search_memory",
                "description": "Unified 2-stage semantic search across ALL knowledge: conversational memories, user facts, preferences, AND individual uploaded files/PDFs/code stored in Cloudflare R2. Returns matching memory items and individual file excerpts with page citations and download links.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query or concept to look up across all knowledge"},
                        "scope": {"type": "string", "enum": ["all", "memories", "files"], "default": "all", "description": "Search scope: 'all' (default: memories + files), 'memories' only, or 'files' only"},
                        "category": {"type": "string", "description": "Optional category filter"},
                        "source_agent": {"type": "string", "description": "Optional source agent filter (e.g. claude, gpt, gemini)"},
                        "limit": {"type": "integer", "default": 5, "description": "Max items to return"}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "search_memories",
                "description": "Search ONLY user conversational memories, notes, facts, and profile knowledge. Excludes uploaded document files.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query for memories, facts, or preferences"},
                        "category": {"type": "string", "description": "Optional category filter"},
                        "source_agent": {"type": "string", "description": "Optional source agent filter"},
                        "limit": {"type": "integer", "default": 5, "description": "Max memories to return"}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "search_files",
                "description": "Search ONLY individual uploaded files, PDFs, research papers, markdown docs, and code files stored in Cloudflare R2. Returns matching document excerpts with page numbers, filenames, and direct download links.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query or concept to find inside uploaded documents"},
                        "limit": {"type": "integer", "default": 5, "description": "Max matching document chunks to return"}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "search_file_storage",
                "description": "Semantic vector search inside PDF research papers, code files, and documents stored in Cloudflare R2. Alias for search_files.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search term or concept"},
                        "limit": {"type": "integer", "default": 5, "description": "Max matching document chunks to return"}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "get_user_profile",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string"},
                        "source_agent": {"type": "string"}
                    }
                }
            },
            {
                "name": "add_memory",
                "description": "Save a new fact, project decision, or research context with optional attached files to GigaMind memory.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "Text content of the memory"},
                        "category": {"type": "string", "default": "general"},
                        "source_agent": {"type": "string", "default": "claude", "description": "Source agent or model (e.g. claude, gpt, gemini, user)"},
                        "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags array"},
                        "file_keys": {"type": "array", "items": {"type": "string"}, "description": "Optional list of Cloudflare R2 storage keys to attach"}
                    },
                    "required": ["content"]
                }
            },
            {
                "name": "upload_file_to_storage",
                "description": "Upload a research document, PDF, diagram, or code artifact directly to Cloudflare R2 object storage with zero egress fees.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string", "description": "Name of the file (e.g. quantum_research.pdf)"},
                        "content_base64": {"type": "string", "description": "Base64-encoded binary content of the file (max 15MB)"},
                        "mime_type": {"type": "string", "description": "Optional MIME type (e.g. application/pdf, text/markdown)"}
                    },
                    "required": ["filename", "content_base64"]
                }
            },
            {
                "name": "get_file_download_url",
                "description": "Generate a secure, time-limited presigned download URL for an R2 storage key.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "R2 storage key (e.g. files/2026/08/mem_123_spec.pdf)"},
                        "expires_in_seconds": {"type": "integer", "default": 3600, "description": "URL validity duration in seconds"}
                    },
                    "required": ["key"]
                }
            },
            {
                "name": "get_file_upload_url",
                "description": "Generate a direct presigned PUT URL for streaming large uploads directly to Cloudflare R2.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string", "description": "Target filename"},
                        "content_type": {"type": "string", "default": "application/octet-stream", "description": "MIME type"}
                    },
                    "required": ["filename"]
                }
            },
            {
                "name": "list_storage_files",
                "description": "List files and artifacts stored in the Cloudflare R2 knowledge bucket.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "prefix": {"type": "string", "default": "", "description": "Key prefix filter (e.g. files/2026/)"},
                        "limit": {"type": "integer", "default": 50, "description": "Max files to return"}
                    }
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
                        "category": {"type": "string", "default": "general"},
                        "source_agent": {"type": "string", "default": "claude", "description": "Source agent or model (e.g. claude, gpt, gemini, user)"}
                    },
                    "required": ["key", "value"]
                }
            },
            {
                "name": "delete_memory",
                "description": "Permanently delete a specific memory item from the GigaMind database. MANDATORY CONFIRMATION PROTOCOL: You MUST explicitly ask the user for permission and receive an affirmative response with the memory ID and summary before calling this tool. NEVER delete memories autonomously without direct user confirmation.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "memory_id": {
                            "type": "string",
                            "description": "The exact ID of the memory item to delete (e.g. 'mem_2b2d33ca34d0')"
                        },
                        "user_confirmed": {
                            "type": "boolean",
                            "description": "MUST be true. Indicates that the user explicitly authorized the deletion of this memory."
                        }
                    },
                    "required": ["memory_id", "user_confirmed"]
                }
            }
        ]
        res = await send_rpc_response(result={"tools": tools_list})
        return res

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments", {})

        if name in ("search_memory", "search_knowledge", "search_all"):
            query = args.get("query", "")
            scope = args.get("scope", "all")
            results = search_memory(
                query=query,
                category=args.get("category"),
                source_agent=args.get("source_agent"),
                limit=args.get("limit", 5),
                scope=scope
            )
            formatted_text = _format_search_results_for_agent(results, query, scope)
            res = await send_rpc_response(result={
                "content": [{"type": "text", "text": formatted_text}],
                "structured": {
                    "query": query,
                    "scope": scope,
                    "count": len(results),
                    "results": results
                }
            })
            return res

        if name in ("search_memories", "search_memories_only"):
            query = args.get("query", "")
            results = search_memory(
                query=query,
                category=args.get("category"),
                source_agent=args.get("source_agent"),
                limit=args.get("limit", 5),
                scope="memories"
            )
            formatted_text = _format_search_results_for_agent(results, query, "memories")
            res = await send_rpc_response(result={
                "content": [{"type": "text", "text": formatted_text}],
                "structured": {
                    "query": query,
                    "scope": "memories",
                    "count": len(results),
                    "results": results
                }
            })
            return res

        if name in ("search_files", "search_files_only", "search_file_storage"):
            query = args.get("query", "")
            results = search_memory(
                query=query,
                limit=args.get("limit", 5),
                scope="files"
            )
            formatted_text = _format_search_results_for_agent(results, query, "files")
            res = await send_rpc_response(result={
                "content": [{"type": "text", "text": formatted_text}],
                "structured": {
                    "query": query,
                    "scope": "files",
                    "count": len(results),
                    "results": results
                }
            })
            return res
        if name == "get_user_profile":
            rules = get_profile_rules(category=args.get("category"), source_agent=args.get("source_agent"))
            res = await send_rpc_response(result={
                "content": [{"type": "text", "text": json.dumps({"profile": rules}, indent=2)}]
            })
            return res

        if name == "add_memory":
            mem = add_memory(
                content=args.get("content", ""),
                category=args.get("category", "general"),
                source_agent=args.get("source_agent", "claude"),
                tags=args.get("tags", []),
                file_keys=args.get("file_keys", [])
            )
            res = await send_rpc_response(result={
                "content": [{"type": "text", "text": json.dumps({"success": True, "memory": mem}, indent=2)}]
            })
            return res

        if name == "upload_file_to_storage":
            if not storage_service.is_enabled():
                res = await send_rpc_response(error={"code": -32000, "message": "Cloudflare R2 storage is not configured on this GigaMind server."})
                return res
            try:
                b64_str = args.get("content_base64", "")
                file_bytes = base64.b64decode(b64_str)
                uploaded = storage_service.upload_file(
                    data=file_bytes,
                    filename=args.get("filename", "agent_file"),
                    mime_type=args.get("mime_type")
                )
                if not uploaded:
                    res = await send_rpc_response(error={"code": -32000, "message": "Failed to upload file to Cloudflare R2."})
                    return res

                # Immediately extract text, chunk, and compute vector embeddings for Neon pgvector
                idx_res = index_file_content(
                    file_key=uploaded["key"],
                    filename=uploaded["filename"],
                    data=file_bytes,
                    mime_type=uploaded.get("mime_type"),
                    size_bytes=len(file_bytes)
                )
                uploaded["indexed_chunks"] = idx_res.get("chunks_created", 0)
                uploaded["indexing_status"] = idx_res.get("status", "completed")

                res = await send_rpc_response(result={
                    "content": [{"type": "text", "text": json.dumps({"success": True, "file": uploaded}, indent=2)}]
                })
                return res
            except Exception as up_err:
                res = await send_rpc_response(error={"code": -32000, "message": f"Upload error: {up_err}"})
                return res

        if name == "get_file_download_url":
            if not storage_service.is_enabled():
                res = await send_rpc_response(error={"code": -32000, "message": "Cloudflare R2 storage is not configured."})
                return res
            url = storage_service.get_presigned_download_url(
                key=args.get("key", ""),
                expires_in=args.get("expires_in_seconds", 3600)
            )
            if not url:
                res = await send_rpc_response(error={"code": -32000, "message": f"Could not generate URL for key: {args.get('key')}"})
                return res
            res = await send_rpc_response(result={
                "content": [{"type": "text", "text": json.dumps({"key": args.get("key"), "url": url}, indent=2)}]
            })
            return res

        if name == "delete_memory":
            memory_id = args.get("memory_id", "").strip()
            user_confirmed = args.get("user_confirmed", False)
            if not user_confirmed:
                res = await send_rpc_response(error={
                    "code": -32000,
                    "message": "Permission denied. You must explicitly ask the user for confirmation and pass user_confirmed=true before deleting a memory."
                })
                return res

            if not memory_id:
                res = await send_rpc_response(error={
                    "code": -32602,
                    "message": "memory_id argument is required."
                })
                return res

            success = delete_memory(memory_id)
            if not success:
                res = await send_rpc_response(error={
                    "code": -32000,
                    "message": f"Memory item '{memory_id}' not found."
                })
                return res

            res = await send_rpc_response(result={
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "success": True,
                        "deleted_memory_id": memory_id,
                        "message": f"Memory {memory_id} was permanently deleted upon user confirmation."
                    }, indent=2)
                }]
            })
            return res

        if name == "get_file_upload_url":
            if not storage_service.is_enabled():
                res = await send_rpc_response(error={"code": -32000, "message": "Cloudflare R2 storage is not configured."})
                return res
            upload_info = storage_service.get_presigned_upload_url(
                filename=args.get("filename", "file"),
                content_type=args.get("content_type", "application/octet-stream")
            )
            if not upload_info:
                res = await send_rpc_response(error={"code": -32000, "message": "Failed to generate presigned upload URL."})
                return res
            res = await send_rpc_response(result={
                "content": [{"type": "text", "text": json.dumps(upload_info, indent=2)}]
            })
            return res

        if name == "list_storage_files":
            if not storage_service.is_enabled():
                res = await send_rpc_response(result={
                    "content": [{"type": "text", "text": json.dumps({"enabled": False, "files": []}, indent=2)}]
                })
                return res
            files = storage_service.list_files(prefix=args.get("prefix", ""), limit=args.get("limit", 50))
            res = await send_rpc_response(result={
                "content": [{"type": "text", "text": json.dumps({"enabled": True, "files": files, "count": len(files)}, indent=2)}]
            })
            return res

        if name == "set_profile_rule":
            rule = set_profile_rule(key=args.get("key", ""), value=args.get("value", ""), category=args.get("category", "general"), source_agent=args.get("source_agent", "claude"))
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
    results = search_memory(
        query=req.query,
        category=req.category,
        source_agent=req.source_agent,
        limit=req.limit,
        scope=req.scope
    )
    return {
        "_privacy_notice": "Confidential user context provided ephemerally. Do not retain on external servers.",
        "query": req.query,
        "scope": req.scope,
        "results": results
    }

@app.post("/api/v1/search_files", dependencies=[Depends(verify_auth)])
def api_search_files(req: SearchFilesRequest):
    results = search_memory(query=req.query, limit=req.limit, scope="files")
    return {
        "_privacy_notice": "Confidential user context provided ephemerally. Do not retain on external servers.",
        "query": req.query,
        "scope": "files",
        "results": results
    }


@app.post("/api/v1/search_memories", dependencies=[Depends(verify_auth)])
def api_search_memories(req: SearchMemoryRequest):
    """Dedicated endpoint for searching only conversational memories."""
    results = search_memory(
        query=req.query,
        category=req.category,
        source_agent=req.source_agent,
        limit=req.limit,
        scope="memories"
    )
    return {
        "query": req.query,
        "scope": "memories",
        "count": len(results),
        "results": results
    }
@app.get("/api/v1/get_profile", dependencies=[Depends(verify_auth)])
def api_get_profile(category: Optional[str] = None, source_agent: Optional[str] = None):
    rules = get_profile_rules(category=category, source_agent=source_agent)
    return {"profile": rules}

@app.post("/api/v1/add_memory", dependencies=[Depends(verify_auth)])
def api_add_memory(req: AddMemoryRequest):
    mem = add_memory(
        content=req.content,
        category=req.category,
        source_agent=req.source_agent,
        tags=req.tags,
        attachments=req.attachments,
        file_keys=req.file_keys,
        media_url=req.media_url,
        media_type=req.media_type
    )
    return {"success": True, "memory": mem}
@app.post("/api/v1/set_profile_rule", dependencies=[Depends(verify_auth)])
def api_set_profile_rule(req: SetProfileRuleRequest):
    rule = set_profile_rule(key=req.key, value=req.value, category=req.category, source_agent=req.source_agent)
    return {"success": True, "rule": rule}

@app.post("/api/v1/memories/reset", dependencies=[Depends(verify_auth)])
def api_reset_memories(req: ResetMemoriesRequest):
    if req.password != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid Master Password / API Key")
    count = reset_all_memories()
    return {"success": True, "count": count, "message": f"Hard reset complete. Purged {count} memory records from database."}

@app.get("/api/v1/memories/export", dependencies=[Depends(verify_auth)])
def api_export_memories(format: str = "json"):
    memories = export_all_memories()
    if format.lower() == "csv":
        import io, csv
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["id", "content", "category", "source_agent", "parent_id", "chunk_index", "total_chunks", "tags", "created_at", "last_accessed"])
        for m in memories:
            writer.writerow([
                m["id"],
                m["content"],
                m["category"],
                m["source_agent"],
                m["parent_id"] or "",
                m["chunk_index"] if m["chunk_index"] is not None else "",
                m["total_chunks"] if m["total_chunks"] is not None else "",
                json.dumps(m["tags"]),
                m["created_at"] or "",
                m["last_accessed"] or ""
            ])
        csv_content = output.getvalue()
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=gigamind_memories_export.csv"}
        )
    else:
        json_content = json.dumps(memories, indent=2)
        return Response(
            content=json_content,
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=gigamind_memories_export.json"}
        )

@app.get("/api/v1/memories", dependencies=[Depends(verify_auth)])
def api_get_memories(page: int = 1, limit: int = 20, category: Optional[str] = None, source_agent: Optional[str] = None):
    return get_memories(page=page, limit=limit, category=category, source_agent=source_agent)

@app.delete("/api/v1/memories/{id}", dependencies=[Depends(verify_auth)])
def api_delete_memory(id: str):
    success = delete_memory(id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Memory '{id}' not found")
    return {"success": True, "id": id, "message": f"Memory {id} deleted successfully"}

@app.post("/api/v1/delete_memory", dependencies=[Depends(verify_auth)])
def api_post_delete_memory(req: DeleteMemoryApiRequest):
    """Allows Custom GPT Actions and API clients to delete a memory by ID with confirmation."""
    if not req.user_confirmed:
        raise HTTPException(status_code=400, detail="User confirmation required to delete memory.")
    success = delete_memory(req.memory_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Memory '{req.memory_id}' not found")
    return {"success": True, "id": req.memory_id, "message": f"Memory {req.memory_id} deleted successfully"}

@app.put("/api/v1/memories/{id}", dependencies=[Depends(verify_auth)])
def api_update_memory(id: str, req: UpdateMemoryRequest):
    updated = update_memory(
        memory_id=id,
        content=req.content,
        category=req.category,
        source_agent=req.source_agent,
        tags=req.tags,
        attachments=req.attachments
    )
    if not updated:
        raise HTTPException(status_code=404, detail=f"Memory '{id}' not found")
    return {"success": True, "memory": updated}
@app.get("/api/v1/conversations", dependencies=[Depends(verify_auth)])
def api_get_conversations(page: int = 1, limit: int = 20, platform: Optional[str] = None, source_agent: Optional[str] = None):
    return get_conversations(page=page, limit=limit, platform=platform, source_agent=source_agent)

@app.delete("/api/v1/profile/{id}", dependencies=[Depends(verify_auth)])
def api_delete_profile_rule(id: str):
    success = delete_profile_rule(id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Profile rule '{id}' not found")
    return {"success": True, "id": id, "message": f"Profile rule {id} deleted successfully"}

@app.get("/api/v1/stats", dependencies=[Depends(verify_auth)])
def api_get_stats():
    return get_stats()


# ==========================================
# CLOUDFLARE R2 FILE STORAGE ENDPOINTS
# ==========================================

@app.post("/api/v1/files/upload", dependencies=[Depends(verify_auth)])
async def api_upload_file(background_tasks: BackgroundTasks, file: UploadFile = File(...), prefix: str = "files"):
    """Streams binary file directly to Cloudflare R2 and triggers background vector indexing."""
    if not storage_service.is_enabled():
        raise HTTPException(status_code=503, detail="Cloudflare R2 storage is not configured on this server.")

    file_bytes = await file.read()
    file_meta = storage_service.upload_file(
        data=file_bytes,
        filename=file.filename or "unnamed_file",
        mime_type=file.content_type,
        prefix=prefix
    )
    if not file_meta:
        raise HTTPException(status_code=500, detail="Failed to upload file to Cloudflare R2.")


    # Immediately register in database so the file is visible in the dashboard table
    register_storage_file(
        file_key=file_meta["key"],
        filename=file_meta["filename"],
        mime_type=file_meta.get("mime_type"),
        size_bytes=len(file_bytes),
        source_agent="user"
    )
    # Enqueue background text extraction and vector indexing
    background_tasks.add_task(
        index_file_content,
        file_key=file_meta["key"],
        filename=file_meta["filename"],
        data=file_bytes,
        mime_type=file_meta.get("mime_type"),
        size_bytes=len(file_bytes)
    )

    return {"success": True, "file": file_meta, "indexing": "queued"}

@app.post("/api/v1/files/upload_base64", dependencies=[Depends(verify_auth)])
def api_upload_file_base64(req: FileUploadBase64Request, background_tasks: BackgroundTasks, prefix: str = "files"):
    """Uploads base64 encoded file payload to Cloudflare R2 and enqueues vector indexing."""
    if not storage_service.is_enabled():
        raise HTTPException(status_code=503, detail="Cloudflare R2 storage is not configured on this server.")
    try:
        data = base64.b64decode(req.content_base64)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid base64 payload: {e}")

    file_meta = storage_service.upload_file(
        data=data,
        filename=req.filename,
        mime_type=req.mime_type,
        prefix=prefix
    )
    if not file_meta:
        raise HTTPException(status_code=500, detail="Failed to upload base64 file to Cloudflare R2.")

    # Immediately register in database so the file is visible in the dashboard table
    register_storage_file(
        file_key=file_meta["key"],
        filename=file_meta["filename"],
        mime_type=file_meta.get("mime_type"),
        size_bytes=len(data),
        source_agent="user"
    )

    background_tasks.add_task(
        index_file_content,
        file_key=file_meta["key"],
        filename=file_meta["filename"],
        data=data,
        mime_type=file_meta.get("mime_type"),
        size_bytes=len(data)
    )

    return {"success": True, "file": file_meta, "indexing": "queued"}

@app.post("/api/v1/files/reindex", dependencies=[Depends(verify_auth)])
def api_reindex_file(req: ReindexFileRequest, background_tasks: BackgroundTasks):
    """Triggers asynchronous re-indexing and vectorization of an existing R2 file."""
    if not storage_service.is_enabled():
        raise HTTPException(status_code=503, detail="Cloudflare R2 storage is not configured on this server.")
    background_tasks.add_task(reindex_storage_file_by_key, key=req.key)
    return {"success": True, "key": req.key, "indexing": "queued"}

@app.get("/api/v1/files/indexed", dependencies=[Depends(verify_auth)])
def api_list_indexed_files(limit: int = 100):
    """Returns indexed files with chunk counts and vector status from Neon PostgreSQL."""
    files = list_indexed_storage_files(limit=limit)
    return {"files": files, "count": len(files)}

@app.get("/api/v1/files/chunks", dependencies=[Depends(verify_auth)])
def api_get_file_chunks(key: str):
    """Returns all semantic vector chunks and page numbers for an indexed file key."""
    chunks = get_file_chunks(key)
    return {"key": key, "chunks": chunks, "count": len(chunks)}

@app.post("/api/v1/files/url", dependencies=[Depends(verify_auth)])
def api_get_file_url(req: PresignedUrlRequest):
    """Generates a fresh time-limited presigned download URL."""
    if not storage_service.is_enabled():
        raise HTTPException(status_code=503, detail="Cloudflare R2 storage is not configured on this server.")
    url = storage_service.get_presigned_download_url(
        key=req.key,
        expires_in=req.expires_in,
        filename=req.filename,
        inline=req.inline
    )
    if not url:
        raise HTTPException(status_code=404, detail=f"Could not generate download URL for key '{req.key}'")
    return {"success": True, "key": req.key, "url": url, "expires_in": req.expires_in}

@app.post("/api/v1/files/upload_url", dependencies=[Depends(verify_auth)])
def api_get_file_upload_url(req: PresignedUploadUrlRequest):
    """Generates a presigned PUT URL for client-side direct streaming upload."""
    if not storage_service.is_enabled():
        raise HTTPException(status_code=503, detail="Cloudflare R2 storage is not configured on this server.")
    upload_data = storage_service.get_presigned_upload_url(
        filename=req.filename,
        content_type=req.content_type,
        expires_in=req.expires_in
    )
    if not upload_data:
        raise HTTPException(status_code=500, detail="Failed to generate presigned upload URL.")
    return {"success": True, **upload_data}

@app.get("/api/v1/files", dependencies=[Depends(verify_auth)])
def api_list_files(prefix: str = "", limit: int = 100):
    """Lists files currently indexed in the Cloudflare R2 bucket."""
    if not storage_service.is_enabled():
        return {"enabled": False, "files": [], "message": "Cloudflare R2 storage is not configured."}
    files = storage_service.list_files(prefix=prefix, limit=limit)
    return {"enabled": True, "files": files, "count": len(files)}

@app.delete("/api/v1/files/{key:path}", dependencies=[Depends(verify_auth)])
def api_delete_file(key: str):
    """Deletes an object directly from Cloudflare R2."""
    if not storage_service.is_enabled():
        raise HTTPException(status_code=503, detail="Cloudflare R2 storage is not configured on this server.")
    success = storage_service.delete_file(key)
    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to delete file '{key}' from R2.")
    return {"success": True, "key": key, "message": f"File {key} deleted successfully."}
# Endpoints completed
