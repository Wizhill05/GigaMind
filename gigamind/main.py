import os
import json
import asyncio
import uuid
import base64
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Request, HTTPException, Depends, Header, Form, UploadFile, File, BackgroundTasks, Query
from contextlib import asynccontextmanager
from sqlalchemy import text, update, or_
import hashlib
import secrets
from gigamind.protocol import create_manager, mcp_endpoint
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict, StrictInt
from gigamind.db.database import init_db
from gigamind.services.storage import storage_service
from gigamind.services.indexing import index_file_content, list_indexed_storage_files, get_file_chunks, register_storage_file
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
    import_conversations_data,
    search_conversations,
    backfill_conversation_vectors,
    delete_conversation,
    vectorize_conversation
)
from gigamind.security import Actor, ClientCredential, SCOPES, create_client, get_actor, public_client, require_scope, now_utc, usable
from gigamind.db.database import engine
from sqlmodel import Session, select
from gigamind.db.trust_models import initialize_trust_tables
from gigamind.db.migrations import schema_ready
from gigamind.routers.review import router as review_router
from gigamind.routers.oauth import router as oauth_router
from gigamind.routers.jobs import router as jobs_router
from gigamind.db import memory_index  # register before migration
from gigamind.services.oauth import resource_config
from gigamind.services import file_lifecycle, jobs

# Initialize DB
resource_config()
init_db()
ClientCredential.__table__.create(engine, checkfirst=True)
initialize_trust_tables(engine)

@asynccontextmanager
async def lifespan(app):
    manager = create_manager()
    async with manager.run():
        yield {'mcp_manager': manager}

app = FastAPI(
    lifespan=lifespan,
    title="GigaMind Personal Memory Engine API",
    description="Single Source of Truth (SSOT) personal memory database for AI models.",
    version="1.0.0",
    openapi_url="/openapi.json"
)
app.include_router(review_router)
app.include_router(oauth_router)
app.include_router(jobs_router)

class MCPMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] in ("/mcp", "/mcp/"):
            await mcp_endpoint(scope, receive, send)
        else:
            await self.app(scope, receive, send)

app.add_middleware(MCPMiddleware)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in os.getenv("GIGAMIND_CORS_ORIGINS", "").split(",") if o],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

frontend_dist_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "dist")
assets_dir = os.path.join(frontend_dist_dir, "assets")
if os.path.exists(assets_dir):
    app.mount("/assets", StaticFiles(directory=assets_dir), name="static_assets")

API_KEY = os.getenv("GIGAMIND_API_KEY", "")

def verify_auth(actor: Actor = Depends(require_scope("admin"))):
    return actor

# Pydantic Request Models
class SearchMemoryRequest(BaseModel):
    query: Optional[str] = Field(None, description="Search query string")
    image_base64: Optional[str] = Field(None, description="Base64 encoded image query for visual similarity search")
    scope: str = Field("all", description="Search domain: 'all' | 'memories' | 'files'")
    category: Optional[str] = Field(None, description="Optional category filter")
    source_agent: Optional[str] = Field(None, description="Optional source agent filter (e.g. claude, gpt, gemini, user)")
    limit: int = Field(5, ge=1, le=100, description="Maximum results to return")

class SearchFilesRequest(BaseModel):
    query: Optional[str] = Field(None, description="Query to search inside uploaded documents")
    image_base64: Optional[str] = Field(None, description="Base64 encoded image query for visual similarity search")
    limit: int = Field(5, ge=1, le=100, description="Maximum results to return")

class SearchMultimodalRequest(BaseModel):
    query: Optional[str] = Field(None, description="Text search query")
    image_base64: Optional[str] = Field(None, description="Base64 encoded image for visual similarity search")
    scope: str = Field("all", description="Search domain: 'all' | 'memories' | 'files'")
    category: Optional[str] = Field(None, description="Optional category filter")
    source_agent: Optional[str] = Field(None, description="Optional source agent filter")
    limit: int = Field(5, ge=1, le=100, description="Maximum results to return")
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
    expected_revision: Optional[int] = Field(None, ge=1)
    content: Optional[str] = Field(None, description="Fact or memory content")
    category: Optional[str] = Field(None, description="Memory category")
    source_agent: Optional[str] = Field(None, description="Source agent or tool (e.g. claude, gpt, gemini, user)")
    tags: Optional[List[str]] = Field(None, description="Tags list")
    attachments: Optional[List[Dict[str, Any]]] = Field(None, description="Updated attachments list")

class ResetMemoriesRequest(BaseModel):
    password: str = Field(..., description="Master API Key / Password to confirm hard memory purge")

class PresignedUrlRequest(BaseModel):
    key: str = Field(..., description="Cloudflare R2 storage key")
    expires_in: StrictInt = Field(3600, ge=1, le=3600, description="Expiration time in seconds, at most one hour")
    filename: Optional[str] = Field(None, max_length=255, description="Optional override filename for Content-Disposition")
    inline: bool = Field(True, description="Inline display (True) or force attachment download (False)")

class PresignedUploadUrlRequest(BaseModel):
    filename: str = Field(..., description="Target file name")
    content_type: str = Field("application/octet-stream", description="File MIME type")
    expires_in: int = Field(3600, description="Expiration time in seconds (default 3600)")

class FileUploadBase64Request(BaseModel):
    filename: str = Field(..., description="File name")
    content_base64: str = Field(..., description="Base64 encoded file content")
    mime_type: Optional[str] = Field(None, description="MIME content type")

class DeleteFileRequest(BaseModel):
    key: str = Field(..., description="Cloudflare R2 storage key to delete")

class ImportConversationsPathRequest(BaseModel):
    file_path: str = Field(..., description="Local path to conversations.json")
    platform: Optional[str] = Field(None, description="Optional platform override (claude, chatgpt)")


class SearchConversationsRequest(BaseModel):
    query: str = Field(..., description="Query to search inside chat transcripts")
    platform: Optional[str] = Field(None, description="Optional platform filter: claude | chatgpt | gemini")
    source_agent: Optional[str] = Field(None, description="Optional source agent filter")
    limit: int = Field(5, ge=1, le=100, description="Maximum results to return")
def _format_search_results_for_agent(results: List[Dict[str, Any]], query: Optional[str], scope: str) -> str:
    query_label = f"'{query}'" if query else "visual multimodal query"
    if not results:
        return f"No matching results found in GigaMind for {query_label} (scope: {scope})."
    lines = [f"Found {len(results)} relevant item(s) for {query_label} (scope: {scope}):\n"]
    file_items = [r for r in results if r.get("source") == "file"]
    mem_items = [r for r in results if r.get("source") != "file"]

    if file_items:
        lines.append("### 📄 Matching Files & Visual Artifacts:")
        for idx, f in enumerate(file_items, 1):
            citation = f.get("citation", f.get("filename", "File"))
            url = f.get("url")
            m_type = f.get("multimodal_type", "").upper()
            type_badge = f" [{m_type}]" if m_type else ""
            link_md = f" | [Download / Open]({url})" if url else ""
            lines.append(f"{idx}. **[{citation}]{type_badge}** (Score: {f.get('score', 0):.2f}){link_md}")
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
        "runtime": "Python (FastAPI + MCP SDK)",
        "dashboard_ui": "/dashboard",
        "mcp_endpoint": "/mcp",
        "openapi_spec": "/openapi.json",
        "legacy_sse": "unavailable",
        "oauth": "external" if resource_config() else "unavailable"
    }
@app.api_route("/oauth/{path:path}", methods=["GET", "POST"])
def oauth_unavailable(path: str):
    raise HTTPException(503, "OAuth is not configured")

@app.api_route("/sse", methods=["GET", "POST"])
@app.api_route("/messages", methods=["GET", "POST"])
def legacy_mcp_unavailable(actor: Actor = Depends(get_actor)):
    raise HTTPException(503, "MCP transport is not configured")


class ClientRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    scopes: List[str] = Field(max_length=100)
    project_ids: List[str] = Field(max_length=100)
    expires_at: Optional[str] = Field(default=None, max_length=64)


class RotationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: StrictInt = Field(ge=0)


@app.get("/api/v1/admin/clients")
def list_clients(
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0, le=100000),
    actor: Actor = Depends(require_scope("admin")),
):
    with Session(engine) as session:
        return {
            "clients": [
                public_client(c)
                for c in session.exec(
                    select(ClientCredential)
                    .order_by(ClientCredential.id)
                    .offset(offset)
                    .limit(limit)
                ).all()
            ]
        }


@app.post("/api/v1/admin/clients")
def add_client(req: ClientRequest, actor: Actor = Depends(require_scope("admin"))):
    if (
        not set(req.scopes).issubset(SCOPES - {"admin"})
        or not req.project_ids
        or any(not p.strip() or len(p) > 200 for p in req.project_ids)
    ):
        raise HTTPException(422, "Valid non-admin scopes and project IDs are required")
    try:
        client, token = create_client(
            req.name, req.scopes, req.project_ids, req.expires_at
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"client": public_client(client), "token": token}


@app.post("/api/v1/admin/clients/{client_id}/rotate")
def rotate_client(
    client_id: str, req: RotationRequest, actor: Actor = Depends(require_scope("admin"))
):
    token = "gm_" + secrets.token_urlsafe(32)
    with Session(engine, expire_on_commit=False) as session:
        client = session.get(ClientCredential, client_id)
        if client is None:
            raise HTTPException(404, "Client not found")
        if not usable(client):
            raise HTTPException(409, "Client cannot be rotated or revision is stale")
        result = session.exec(
            update(ClientCredential)
            .where(
                ClientCredential.id == client_id,
                ClientCredential.revoked == False,
                ClientCredential.revision == req.expected_revision,
                or_(
                    ClientCredential.expires_at == None,
                    ClientCredential.expires_at > now_utc().isoformat(),
                ),
            )
            .values(
                token_hash=hashlib.sha256(token.encode()).hexdigest(),
                revision=ClientCredential.revision + 1,
            )
        )
        if result.rowcount != 1:
            session.rollback()
            if not session.get(ClientCredential, client_id):
                raise HTTPException(404, "Client not found")
            raise HTTPException(409, "Client cannot be rotated or revision is stale")
        session.commit()
        client = session.get(ClientCredential, client_id)
        return {"client": public_client(client), "token": token}


@app.post("/api/v1/admin/clients/{client_id}/revoke")
def revoke_client(client_id: str, actor: Actor = Depends(require_scope("admin"))):
    with Session(engine) as session:
        client = session.get(ClientCredential, client_id)
        if not client:
            raise HTTPException(404, "Client not found")
        client.revoked = True
        session.add(client)
        session.commit()
        return {"client": public_client(client)}


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/ready")
def ready():
    key = os.getenv("GIGAMIND_API_KEY", "")
    if not key or key == "gigamind-secret-key-change-me":
        raise HTTPException(503, "Admin credential is not configured")
    try:
        ready_schema = schema_ready(engine)
    except Exception:
        raise HTTPException(503, "Database unavailable")
    if not ready_schema:
        raise HTTPException(503, "Database schema is not ready")
    return {"status": "ready"}


# ==========================================
# REST API ENDPOINTS (ChatGPT & Gemini)
# ==========================================


@app.post("/api/v1/search_memory", dependencies=[Depends(verify_auth)])
def api_search_memory(req: SearchMemoryRequest):
    results = search_memory(
        query=req.query,
        query_image_base64=req.image_base64,
        category=req.category,
        source_agent=req.source_agent,
        limit=req.limit,
        scope=req.scope,
    )
    return {
        "_privacy_notice": "Confidential user context provided ephemerally. Do not retain on external servers.",
        "query": req.query,
        "scope": req.scope,
        "results": results
    }

@app.post("/api/v1/search_multimodal", dependencies=[Depends(verify_auth)])
def api_search_multimodal(req: SearchMultimodalRequest):
    """Direct multimodal search endpoint accepting text and/or image queries."""
    results = search_memory(
        query=req.query,
        query_image_base64=req.image_base64,
        category=req.category,
        source_agent=req.source_agent,
        limit=req.limit,
        scope=req.scope
    )
    return {
        "query": req.query,
        "scope": req.scope,
        "count": len(results),
        "results": results
    }

@app.post("/api/v1/search_files", dependencies=[Depends(verify_auth)])
def api_search_files(req: SearchFilesRequest):
    results = search_memory(query=req.query, query_image_base64=req.image_base64, limit=req.limit, scope="files")
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
def api_get_memories(page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100), category: Optional[str] = None, source_agent: Optional[str] = None, q: Optional[str] = None):
    return get_memories(page=page, limit=limit, category=category, source_agent=source_agent, q=q)

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
        attachments=req.attachments,
        expected_revision=req.expected_revision
    )
    if not updated:
        raise HTTPException(status_code=404, detail=f"Memory '{id}' not found")
    return {"success": True, "memory": updated}
@app.get("/api/v1/conversations", dependencies=[Depends(verify_auth)])
def api_get_conversations(page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100), platform: Optional[str] = None, source_agent: Optional[str] = None):
    return get_conversations(page=page, limit=limit, platform=platform, source_agent=source_agent)


@app.delete("/api/v1/conversations/{id}", dependencies=[Depends(verify_auth)])
def api_delete_conversation(id: str):
    """Deletes a conversation transcript log by ID."""
    success = delete_conversation(id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Conversation '{id}' not found")
    return {"success": True, "id": id, "message": f"Conversation {id} deleted successfully"}

@app.post("/api/v1/conversations/{id}/vectorize", dependencies=[Depends(verify_auth)])
def api_vectorize_conversation(id: str):
    """Vectorizes a single conversation transcript using Gemini Embedding 2."""
    success = vectorize_conversation(id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Conversation '{id}' not found")
    return {"success": True, "id": id, "message": f"Conversation {id} vectorized successfully"}
@app.delete("/api/v1/profile/{id}", dependencies=[Depends(verify_auth)])
def api_delete_profile_rule(id: str):
    success = delete_profile_rule(id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Profile rule '{id}' not found")
    return {"success": True, "id": id, "message": f"Profile rule {id} deleted successfully"}

@app.post("/api/v1/conversations/import_file", dependencies=[Depends(verify_auth)])
async def api_import_conversations_file(file: UploadFile = File(...), platform: Optional[str] = None):
    """Uploads and batch-imports conversations.json from Claude, ChatGPT, or standard exports."""
    from gigamind.services.conversation_import import MAX_BYTES

    try:
        content = await file.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise HTTPException(413, 'Conversation import exceeds size limit')
        return await asyncio.to_thread(import_conversations_data, content, default_platform=platform)
    except ValueError as exc:
        raise HTTPException(400, str(exc)[:300]) from None
    finally:
        await file.close()

@app.post("/api/v1/conversations/import_path", dependencies=[Depends(verify_auth)])
def api_import_conversations_path(req: ImportConversationsPathRequest):
    raise HTTPException(403, "Server-path import is disabled; upload a file instead")


@app.post("/api/v1/conversations/search", dependencies=[Depends(verify_auth)])
@app.post("/api/v1/search_conversations", dependencies=[Depends(verify_auth)])
def api_search_conversations(req: SearchConversationsRequest):
    """Semantic vector search across chat conversation sessions and transcripts."""
    results = search_conversations(
        query=req.query,
        platform=req.platform,
        source_agent=req.source_agent,
        limit=req.limit
    )
    return {
        "query": req.query,
        "platform": req.platform,
        "count": len(results),
        "results": results
    }

@app.post("/api/v1/conversations/backfill_vectors", dependencies=[Depends(verify_auth)])
def api_backfill_conversation_vectors(background_tasks: BackgroundTasks):
    """Asynchronously computes and backfills vector embeddings for all chat logs."""
    background_tasks.add_task(backfill_conversation_vectors)
    return {"success": True, "message": "Backfill vector indexing started in background."}
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


@app.post("/api/v1/files/reindex", status_code=202, dependencies=[Depends(verify_auth)])
def api_reindex_file(req: ReindexFileRequest):
    file_lifecycle.validate_key(req.key)
    try:
        job = jobs.enqueue("index_file", {"key": req.key})
    except jobs.Conflict as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"key": req.key, "job_id": job.id, "state": job.state}


@app.get("/api/v1/files/indexed", dependencies=[Depends(verify_auth)])
def api_list_indexed_files(limit: int = Query(100, ge=1, le=100)):
    """Returns indexed files with chunk counts and vector status from Neon PostgreSQL."""
    files = list_indexed_storage_files(limit=limit)
    deleted = file_lifecycle.tombstoned_keys([f["key"] for f in files])
    files = [f for f in files if f["key"] not in deleted]
    return {"files": files, "count": len(files)}


@app.get("/api/v1/files/chunks", dependencies=[Depends(verify_auth)])
def api_get_file_chunks(key: str):
    """Returns all semantic vector chunks and page numbers for an indexed file key."""
    with file_lifecycle.active_access(key):
        chunks = get_file_chunks(key)
    return {"key": key, "chunks": chunks, "count": len(chunks)}


@app.post("/api/v1/files/url", dependencies=[Depends(verify_auth)])
def api_get_file_url(req: PresignedUrlRequest):
    """Generates a fresh time-limited presigned download URL."""
    file_lifecycle.require_active(req.key)
    if not storage_service.is_enabled():
        raise HTTPException(
            status_code=503,
            detail="Cloudflare R2 storage is not configured on this server.",
        )
    url = file_lifecycle.download_url(
        key=req.key, expires_in=req.expires_in, filename=req.filename, inline=req.inline
    )
    if not url:
        raise HTTPException(
            status_code=404,
            detail=f"Could not generate download URL for key '{req.key}'",
        )
    return {"success": True, "key": req.key, "url": url, "expires_in": req.expires_in}


@app.post("/api/v1/files/upload_url", dependencies=[Depends(verify_auth)])
def api_get_file_upload_url(req: PresignedUploadUrlRequest):
    raise HTTPException(
        410,
        "Direct upload URLs are unavailable until an upload completion protocol is supported. Use the file upload endpoint.",
    )


@app.get("/api/v1/files", dependencies=[Depends(verify_auth)])
def api_list_files(
    prefix: str = Query("", max_length=1024), limit: int = Query(100, ge=1, le=100)
):
    """Lists files currently indexed in the Cloudflare R2 bucket."""
    if len(prefix.encode("utf-8")) > 1024:
        raise HTTPException(422, "Prefix must be at most 1024 UTF-8 bytes")
    if not storage_service.is_enabled():
        return {
            "enabled": False,
            "files": [],
            "message": "Cloudflare R2 storage is not configured.",
        }
    files = storage_service.list_files(prefix=prefix, limit=limit)
    deleted = file_lifecycle.tombstoned_keys([f["key"] for f in files])
    retained = []
    for file in files:
        if file["key"] in deleted:
            continue
        try:
            file["url"] = file_lifecycle.download_url(
                file["key"], filename=file.get("filename")
            )
        except HTTPException as exc:
            if exc.status_code == 409:
                continue
            raise
        retained.append(file)
    return {"enabled": True, "files": retained, "count": len(retained)}


def delete_file_response(key: str, actor: Actor):
    job = file_lifecycle.request_delete(actor, key)
    return {
        "key": key,
        "job_id": job.id,
        "state": job.state,
        "cleanup": "completed" if job.state == "completed" else "pending",
    }


@app.post("/api/v1/files/delete", status_code=202)
def api_post_delete_file(
    req: DeleteFileRequest, actor: Actor = Depends(require_scope("admin"))
):
    return delete_file_response(req.key, actor)


@app.delete("/api/v1/files/{key:path}", status_code=202)
def api_delete_file(key: str, actor: Actor = Depends(require_scope("admin"))):
    return delete_file_response(key, actor)
