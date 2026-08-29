import json
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from sqlmodel import Session, select, text
from gigamind.db.database import engine, is_postgres, ProfileItem, MemoryItem, ConversationItem, TaskSessionItem, StorageFileItem, StorageChunkItem
from gigamind.services.embedding import generate_embedding, cosine_similarity
from gigamind.services.chunking import chunk_text
from gigamind.services.reranker import rerank_candidates
from gigamind.services.storage import storage_service
from gigamind.services.indexing import delete_storage_file_index, delete_all_storage_file_indexes, register_storage_file


def _hydrate_attachments(attachments_raw: Any, media_url: Optional[str] = None, media_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """Parse attachments_json and inject active presigned download URLs."""
    items: List[Dict[str, Any]] = []
    if isinstance(attachments_raw, str):
        try:
            items = json.loads(attachments_raw or "[]")
        except Exception:
            items = []
    elif isinstance(attachments_raw, list):
        items = list(attachments_raw)

    # Legacy media_url fallback if attachments is empty
    if not items and media_url:
        items = [{
            "key": media_url,
            "filename": media_url.split("/")[-1] or "legacy_attachment",
            "mime_type": media_type or "application/octet-stream",
            "size_bytes": 0,
            "url": media_url,
            "created_at": datetime.now(timezone.utc).isoformat()
        }]

    hydrated = []
    for att in items:
        if not isinstance(att, dict):
            continue
        key = att.get("key", "")
        filename = att.get("filename") or (key.split("/")[-1] if key else "attachment")
        url = att.get("url", "")
        # Generate fresh presigned download URL if storage is enabled and key is not an external HTTP URL
        if key and storage_service.is_enabled() and not (url and url.startswith("http") and ("r2.cloudflarestorage.com" not in url)):
            fresh_url = storage_service.get_presigned_download_url(key, filename=filename)
            if fresh_url:
                url = fresh_url

        hydrated.append({
            "key": key or "",
            "filename": filename,
            "mime_type": att.get("mime_type") or "application/octet-stream",
            "size_bytes": att.get("size_bytes", 0),
            "url": url or "",
            "created_at": att.get("created_at") or datetime.now(timezone.utc).isoformat()
        })
    return hydrated
def search_memory(
    query: Optional[str] = None,
    query_image_base64: Optional[str] = None,
    category: Optional[str] = None,
    source_agent: Optional[str] = None,
    limit: int = 5,
    scope: str = "all"
) -> List[Dict[str, Any]]:
    """
    Hierarchical Multimodal 2-Stage RAG Search Engine:
    - Ingests text queries or visual image queries (base64) using Gemini Embedding 2.
    - Hierarchical Fusion: Combines whole-document holistic vectors (storage_files)
      with surgical page/visual snippet vectors (storage_chunks).
    - Stage 2: Cross-Encoder Neural Rerank Pass (Top limit unique items returned).
    """
    scope_clean = (scope or "all").lower().strip()
    if scope_clean not in ("all", "memories", "files"):
        scope_clean = "all"

    query_vector = generate_embedding(
        text=query if query else None,
        image_base64=query_image_base64,
        mime_type="image/png"
    )
    query_lower = (query or "").lower()
    query_keywords = [k for k in re_words if len(k) > 2] if (re_words := query_lower.split()) else []

    candidates: List[Dict[str, Any]] = []

    with Session(engine) as session:
        # ====================================================
        # 1. MEMORIES & PROFILE RULES SCAN (if scope: all | memories)
        # ====================================================
        if scope_clean in ("all", "memories"):
            raw_mem_candidates: List[Dict[str, Any]] = []
            if is_postgres:
                try:
                    vector_str = f"[{','.join(str(x) for x in query_vector)}]"
                    sql = """
                    SELECT id, content, category, source_agent, parent_id, chunk_index, total_chunks, tags_json, attachments_json,
                           1.0 - (embedding_vector <=> CAST(:vec AS vector)) AS vector_score
                    FROM memories
                    WHERE embedding_vector IS NOT NULL
                    ORDER BY embedding_vector <=> CAST(:vec AS vector) ASC
                    LIMIT 40;
                    """
                    rows = session.exec(text(sql), params={"vec": vector_str}).all()
                    for r in rows:
                        raw_mem_candidates.append({
                            "id": r.id,
                            "source": "memory",
                            "content": r.content,
                            "category": r.category,
                            "source_agent": r.source_agent or "user",
                            "parent_id": r.parent_id,
                            "chunk_index": r.chunk_index,
                            "total_chunks": r.total_chunks,
                            "tags": json.loads(r.tags_json or "[]"),
                            "attachments": _hydrate_attachments(r.attachments_json),
                            "score": float(r.vector_score or 0.0),
                            "vector_score": float(r.vector_score or 0.0)
                        })
                except Exception as pg_err:
                    print(f"pgvector query note: {pg_err}")
                    session.rollback()

            # Keyword scan for memories
            keyword_memories = session.exec(select(MemoryItem).limit(60)).all()
            for mem in keyword_memories:
                kw_score = 0.0
                mem_lower = mem.content.lower()
                kw_hits = sum(1 for kw in query_keywords if kw in mem_lower)
                if query_keywords:
                    kw_score = (kw_hits / len(query_keywords)) * 0.4

                if kw_score > 0.1:
                    raw_mem_candidates.append({
                        "id": mem.id,
                        "source": "memory",
                        "content": mem.content,
                        "category": mem.category,
                        "source_agent": getattr(mem, "source_agent", "user") or "user",
                        "parent_id": mem.parent_id,
                        "chunk_index": mem.chunk_index,
                        "total_chunks": mem.total_chunks,
                        "tags": json.loads(mem.tags_json or "[]"),
                        "attachments": _hydrate_attachments(mem.attachments_json, mem.media_url, mem.media_type),
                        "score": round(kw_score, 4)
                    })

            # Deduplicate memory chunks by parent memory
            distinct_mem_map: Dict[str, Dict[str, Any]] = {}
            for mc in raw_mem_candidates:
                pkey = mc.get("parent_id") or mc.get("id")
                if pkey not in distinct_mem_map or mc["score"] > distinct_mem_map[pkey]["score"]:
                    distinct_mem_map[pkey] = mc

            candidates.extend(distinct_mem_map.values())

            # Profile rules scan
            profiles = session.exec(select(ProfileItem)).all()
            for prof in profiles:
                p_text = f"{prof.key}: {prof.value}".lower()
                p_score = 0.0
                for kw in query_keywords:
                    if kw in p_text:
                        p_score += 0.4

                if p_score > 0.1:
                    candidates.append({
                        "id": prof.id,
                        "source": "profile",
                        "content": f"[PROFILE RULE] {prof.key} = {prof.value}",
                        "category": prof.category,
                        "source_agent": getattr(prof, "source_agent", "user") or "user",
                        "score": round(p_score, 4)
                    })
        # ====================================================
        # 2. VECTORIZED OBJECT STORAGE SCAN (if scope: all | files)
        # ====================================================
        if scope_clean in ("all", "files"):
            distinct_files_map: Dict[str, Dict[str, Any]] = {}
            if is_postgres:
                try:
                    vector_str = f"[{','.join(str(x) for x in query_vector)}]"

                    # 1. Whole-Document Holistic Candidates Scan
                    sql_docs = """
                    SELECT id, key, filename, mime_type, multimodal_type, document_summary,
                           1.0 - (embedding_vector <=> CAST(:vec AS vector)) AS vector_score
                    FROM storage_files
                    WHERE embedding_vector IS NOT NULL
                    ORDER BY embedding_vector <=> CAST(:vec AS vector) ASC
                    LIMIT 30;
                    """
                    doc_rows = session.exec(text(sql_docs), params={"vec": vector_str}).all()
                    for dr in doc_rows:
                        url = None
                        if storage_service.is_enabled():
                            url = storage_service.get_presigned_download_url(dr.key, filename=dr.filename)

                        distinct_files_map[dr.key] = {
                            "id": dr.id,
                            "file_id": dr.id,
                            "file_key": dr.key,
                            "filename": dr.filename,
                            "mime_type": dr.mime_type,
                            "multimodal_type": dr.multimodal_type or "text",
                            "content": dr.document_summary or f"[{dr.multimodal_type.upper()}: {dr.filename}]",
                            "score": float(dr.vector_score or 0.0),
                            "doc_vector_score": float(dr.vector_score or 0.0),
                            "chunk_index": 0,
                            "total_chunks": 1,
                            "matching_pages": [],
                            "url": url or "",
                            "source": "file",
                            "category": "file"
                        }

                    # 2. Page-Level & Visual Snippet Candidates Scan
                    sql_chunks = """
                    SELECT id, file_id, file_key, filename, chunk_index, total_chunks, page_number, is_visual_anchor, content,
                           1.0 - (embedding_vector <=> CAST(:vec AS vector)) AS vector_score
                    FROM storage_chunks
                    WHERE embedding_vector IS NOT NULL
                    ORDER BY embedding_vector <=> CAST(:vec AS vector) ASC
                    LIMIT 60;
                    """
                    chunk_rows = session.exec(text(sql_chunks), params={"vec": vector_str}).all()
                    for cr in chunk_rows:
                        fkey = cr.file_key
                        chunk_score = float(cr.vector_score or 0.0)
                        if fkey not in distinct_files_map:
                            url = None
                            if storage_service.is_enabled():
                                url = storage_service.get_presigned_download_url(fkey, filename=cr.filename)

                            distinct_files_map[fkey] = {
                                "id": cr.id,
                                "file_id": cr.file_id,
                                "file_key": cr.file_key,
                                "filename": cr.filename,
                                "content": cr.content,
                                "page_number": cr.page_number,
                                "chunk_index": cr.chunk_index,
                                "total_chunks": cr.total_chunks,
                                "score": chunk_score,
                                "matching_pages": [cr.page_number] if cr.page_number is not None else [],
                                "url": url or "",
                                "source": "file",
                                "category": "file"
                            }
                        else:
                            target = distinct_files_map[fkey]
                            # Hierarchical fusion: 0.6 * page_score + 0.4 * doc_score
                            doc_score = target.get("doc_vector_score", chunk_score)
                            fused_score = round(0.6 * chunk_score + 0.4 * doc_score, 4)
                            if chunk_score > target["score"]:
                                target["content"] = cr.content
                                target["score"] = fused_score
                                target["chunk_index"] = cr.chunk_index
                                target["total_chunks"] = cr.total_chunks
                                target["page_number"] = cr.page_number
                            if cr.page_number is not None and cr.page_number not in target["matching_pages"]:
                                target["matching_pages"].append(cr.page_number)
                except Exception as pg_hier_err:
                    print(f"pgvector hierarchical search note: {pg_hier_err}")
                    session.rollback()

            # Fallback SQLite candidate scanner
            if not distinct_files_map:
                s_files = session.exec(select(StorageFileItem).limit(40)).all()
                for sf in s_files:
                    f_score = 0.0
                    try:
                        sf_vec = json.loads(sf.embedding_json)
                        f_score += cosine_similarity(query_vector, sf_vec) * 0.7
                    except Exception:
                        pass
                    sf_lower = sf.filename.lower() + " " + (sf.document_summary or "").lower()
                    kw_hits = sum(1 for kw in query_keywords if kw in sf_lower)
                    if query_keywords:
                        f_score += (kw_hits / len(query_keywords)) * 0.3

                    if f_score > 0.05:
                        url = None
                        if storage_service.is_enabled():
                            url = storage_service.get_presigned_download_url(sf.key, filename=sf.filename)
                        distinct_files_map[sf.key] = {
                            "id": sf.id,
                            "file_id": sf.id,
                            "file_key": sf.key,
                            "filename": sf.filename,
                            "content": sf.document_summary or f"[{sf.filename}]",
                            "score": round(f_score, 4),
                            "url": url or "",
                            "matching_pages": [],
                            "source": "file",
                            "category": "file"
                        }

            candidates.extend(distinct_files_map.values())
    # Sort all candidates by initial score
    candidates.sort(key=lambda x: x["score"], reverse=True)
    top_candidates = candidates[:50]

    # ====================================================
    # STAGE 2: CROSS-ENCODER NEURAL RERANK PASS
    # ====================================================
    reranked_results = rerank_candidates(query=query or "visual and multimodal search", candidates=top_candidates, top_n=limit)

    final_output = []
    for item in reranked_results:
        src = item.get("source", "memory")
        if src == "file":
            res_item = {
                "id": item["id"],
                "source": "file",
                "content": item["content"],
                "filename": item.get("filename", ""),
                "file_key": item.get("file_key", ""),
                "file_id": item.get("file_id", ""),
                "multimodal_type": item.get("multimodal_type", "text"),
                "page_number": item.get("page_number"),
                "chunk_index": item.get("chunk_index", 0),
                "total_chunks": item.get("total_chunks", 1),
                "score": item["score"],
                "vector_score": item.get("vector_score", item["score"]),
                "rerank_score": item.get("rerank_score", item["score"]),
                "url": item.get("url", "")
            }
            if item.get("matching_pages"):
                pages_str = ", ".join(str(p) for p in sorted(item["matching_pages"]))
                res_item["citation"] = f"{item.get('filename')} (Page{'s' if len(item['matching_pages']) > 1 else ''} {pages_str})"
            elif item.get("page_number") is not None:
                res_item["citation"] = f"{item.get('filename')} (Page {item.get('page_number')})"
            else:
                res_item["citation"] = f"{item.get('filename')} (Chunk {item.get('chunk_index', 0) + 1}/{item.get('total_chunks', 1)})"
        else:
            res_item = {
                "id": item["id"],
                "source": src,
                "content": item["content"],
                "category": item.get("category", "general"),
                "source_agent": item.get("source_agent", "user"),
                "score": item["score"],
                "vector_score": item.get("vector_score", item["score"]),
                "rerank_score": item.get("rerank_score", item["score"]),
                "parent_id": item.get("parent_id"),
                "tags": item.get("tags", []),
                "attachments": item.get("attachments", [])
            }
            if item.get("chunk_index") is not None:
                res_item["chunk_info"] = {
                    "index": item["chunk_index"],
                    "total": item.get("total_chunks", 1)
                }

        final_output.append(res_item)

    return final_output

def add_memory(
    content: str,
    category: str = "general",
    source_agent: str = "user",
    tags: Optional[List[str]] = None,
    attachments: Optional[List[Dict[str, Any]]] = None,
    file_keys: Optional[List[str]] = None,
    media_url: Optional[str] = None,
    media_type: Optional[str] = None
) -> Dict[str, Any]:
    if tags is None:
        tags = []

    now_str = datetime.now(timezone.utc).isoformat()
    parent_mem_id = f"mem_{uuid.uuid4().hex[:12]}"

    resolved_attachments: List[Dict[str, Any]] = []
    if attachments:
        resolved_attachments.extend(attachments)
    if file_keys:
        for fk in file_keys:
            if fk and isinstance(fk, str):
                resolved_attachments.append({
                    "key": fk,
                    "filename": fk.split("/")[-1],
                    "mime_type": "application/octet-stream",
                    "size_bytes": 0,
                    "created_at": now_str
                })
    if media_url and not resolved_attachments:
        resolved_attachments.append({
            "key": media_url,
            "filename": media_url.split("/")[-1] or "attachment",
            "mime_type": media_type or "application/octet-stream",
            "size_bytes": 0,
            "created_at": now_str
        })


    # Automatically register all attached files in the Storage Files repository
    for att in resolved_attachments:
        f_key = att.get("key")
        if f_key:
            try:
                register_storage_file(
                    file_key=f_key,
                    filename=att.get("filename") or f_key.split("/")[-1],
                    mime_type=att.get("mime_type"),
                    size_bytes=att.get("size_bytes", 0),
                    source_agent=source_agent or "user"
                )
            except Exception as reg_err:
                print(f"Attachment storage registration note: {reg_err}")
    attachments_json_str = json.dumps(resolved_attachments)
    chunks = chunk_text(content, chunk_size=500, chunk_overlap=100, min_threshold=600)

    with Session(engine) as session:
        if len(chunks) <= 1:
            # Single short memory item
            embedding = generate_embedding(content)
            item = MemoryItem(
                id=parent_mem_id,
                content=content,
                category=category,
                media_type=media_type or "text",
                media_url=media_url,
                source_agent=source_agent or "user",
                tags_json=json.dumps(tags),
                embedding_json=json.dumps(embedding),
                attachments_json=attachments_json_str,
                parent_id=None,
                chunk_index=None,
                total_chunks=None,
                created_at=now_str,
                last_accessed=now_str
            )
            session.add(item)
            session.commit()
            if is_postgres:
                try:
                    vec_str = f"[{','.join(str(x) for x in embedding)}]"
                    with Session(engine) as p_sess:
                        p_sess.exec(text("UPDATE memories SET embedding_vector = CAST(:vec AS vector) WHERE id = :id"), params={"vec": vec_str, "id": parent_mem_id})
                        p_sess.commit()
                except Exception as p_err:
                    print(f"pgvector single chunk update note: {p_err}")
            return {
                "id": parent_mem_id,
                "content": content,
                "category": category,
                "source_agent": source_agent or "user",
                "tags": tags,
                "attachments": _hydrate_attachments(resolved_attachments),
                "chunks_created": 1,
                "created_at": now_str
            }

        # Multi-chunk memory insertion
        # 1. Parent Memory Record
        parent_item = MemoryItem(
            id=parent_mem_id,
            content=content,
            category=category,
            media_type=media_type or "text",
            media_url=media_url,
            source_agent=source_agent or "user",
            tags_json=json.dumps(tags),
            embedding_json="[]",
            attachments_json=attachments_json_str,
            parent_id=None,
            chunk_index=None,
            total_chunks=len(chunks),
            created_at=now_str,
            last_accessed=now_str
        )
        session.add(parent_item)

        # 2. Child Chunk Records (Denormalize attachments_json to ensure search_memory preserves files)
        for chk in chunks:
            chk_id = f"{parent_mem_id}_chk_{chk['chunk_index']}"
            chk_embedding = generate_embedding(chk["content"])
            chk_item = MemoryItem(
                id=chk_id,
                content=chk["content"],
                category=category,
                media_type=media_type or "text",
                media_url=media_url,
                source_agent=source_agent or "user",
                tags_json=json.dumps(tags),
                embedding_json=json.dumps(chk_embedding),
                attachments_json=attachments_json_str,
                parent_id=parent_mem_id,
                chunk_index=chk["chunk_index"],
                total_chunks=chk["total_chunks"],
                created_at=now_str,
                last_accessed=now_str
            )
            session.add(chk_item)

        session.commit()
        if is_postgres:
            try:
                with Session(engine) as p_sess:
                    for chk in chunks:
                        chk_id = f"{parent_mem_id}_chk_{chk['chunk_index']}"
                        chk_emb = generate_embedding(chk["content"])
                        chk_vec_str = f"[{','.join(str(x) for x in chk_emb)}]"
                        p_sess.exec(text("UPDATE memories SET embedding_vector = CAST(:vec AS vector) WHERE id = :id"), params={"vec": chk_vec_str, "id": chk_id})
                    p_sess.commit()
            except Exception as p_err:
                print(f"pgvector multi-chunk update note: {p_err}")

    return {
        "id": parent_mem_id,
        "content": content[:150] + "...",
        "category": category,
        "source_agent": source_agent or "user",
        "tags": tags,
        "attachments": _hydrate_attachments(resolved_attachments),
        "chunks_created": len(chunks),
        "created_at": now_str
    }


def set_profile_rule(key: str, value: str, category: str = "general", source_agent: str = "user") -> Dict[str, Any]:
    prof_id = f"prof_{key.replace(' ', '_')}"
    now_str = datetime.now(timezone.utc).isoformat()

    with Session(engine) as session:
        existing = session.exec(select(ProfileItem).where(ProfileItem.key == key)).first()
        if existing:
            existing.value = value
            existing.category = category
            existing.source_agent = source_agent or "user"
            existing.updated_at = now_str
        else:
            item = ProfileItem(
                id=prof_id,
                key=key,
                value=value,
                category=category,
                source_agent=source_agent or "user",
                updated_at=now_str
            )
            session.add(item)
        session.commit()

    return {
        "id": prof_id,
        "key": key,
        "value": value,
        "category": category,
        "source_agent": source_agent or "user",
        "updated_at": now_str
    }

def get_profile_rules(category: Optional[str] = None, source_agent: Optional[str] = None) -> List[Dict[str, Any]]:
    with Session(engine) as session:
        stmt = select(ProfileItem)
        if category:
            stmt = stmt.where(ProfileItem.category == category)
        if source_agent:
            stmt = stmt.where(ProfileItem.source_agent == source_agent)
        items = session.exec(stmt).all()
        return [{
            "id": i.id,
            "key": i.key,
            "value": i.value,
            "category": i.category,
            "source_agent": getattr(i, "source_agent", "user") or "user",
            "updated_at": i.updated_at
        } for i in items]

def add_conversation_log(platform: str, title: str, summary: str, messages: List[Dict[str, Any]], source_agent: str = "user") -> Dict[str, Any]:
    conv_id = f"conv_{platform}_{uuid.uuid4().hex[:8]}"
    msgs_preview = "\n".join(f"{m.get('role', 'user')}: {m.get('content', '')[:100]}" for m in messages[:5])
    text_for_vector = f"Chat Platform: {platform}. Title: {title}\nSummary: {summary}\n{msgs_preview}"
    embedding = generate_embedding(text_for_vector)
    now_str = datetime.now(timezone.utc).isoformat()

    item = ConversationItem(
        id=conv_id,
        platform=platform,
        title=title,
        summary=summary,
        source_agent=source_agent or "user",
        messages_json=json.dumps(messages),
        embedding_json=json.dumps(embedding),
        created_at=now_str
    )

    with Session(engine) as session:
        session.add(item)
        session.commit()
        if is_postgres:
            try:
                with Session(engine) as p_sess:
                    vec_str = f"[{','.join(str(x) for x in embedding)}]"
                    p_sess.exec(text("UPDATE conversations SET embedding_vector = CAST(:vec AS vector) WHERE id = :id"), params={"vec": vec_str, "id": conv_id})
                    p_sess.commit()
            except Exception as p_err:
                print(f"conversations pgvector update note: {p_err}")

    return {
        "id": conv_id,
        "platform": platform,
        "title": title,
        "summary": summary,
        "source_agent": source_agent or "user",
        "created_at": now_str
    }

def import_conversations_data(raw_data: Any, default_platform: Optional[str] = None) -> Dict[str, Any]:
    """
    Parses and batch-inserts exported chat history from Claude, ChatGPT, or generic JSON.
    Extracts title, messages, timestamps, and preserves full transcripts.
    """
    if isinstance(raw_data, (bytes, bytearray)):
        try:
            raw_data = raw_data.decode("utf-8")
        except UnicodeDecodeError:
            raw_data = raw_data.decode("latin-1")

    if isinstance(raw_data, str):
        try:
            conversations = json.loads(raw_data)
        except Exception as e:
            raise ValueError(f"Invalid JSON payload: {e}")
    elif isinstance(raw_data, list):
        conversations = raw_data
    elif isinstance(raw_data, dict):
        conversations = [raw_data]
    else:
        raise ValueError("Unsupported data format for conversations import.")

    ingested_count = 0
    skipped_count = 0

    with Session(engine) as session:
        for conv in conversations:
            if not isinstance(conv, dict):
                continue

            # Format A: Claude Export (contains chat_messages list)
            if "chat_messages" in conv:
                platform = default_platform or "claude"
                source_agent = "claude"
                conv_uuid = conv.get("uuid") or f"claude_{uuid.uuid4().hex[:8]}"
                conv_id = f"conv_claude_{conv_uuid.replace('-', '')[:12]}"
                title = conv.get("name") or conv.get("summary") or "Untitled Claude Conversation"
                created_at = conv.get("created_at") or datetime.now(timezone.utc).isoformat()

                chat_msgs = conv.get("chat_messages", [])
                messages = []
                for m in chat_msgs:
                    sender = "user" if m.get("sender") == "human" else ("assistant" if m.get("sender") == "assistant" else "system")
                    text_content = m.get("text") or ""
                    if isinstance(m.get("content"), list):
                        text_content = "\n".join(c.get("text", "") for c in m["content"] if isinstance(c, dict) and "text" in c)
                    if text_content.strip():
                        messages.append({"role": sender, "content": text_content.strip()})

            # Format B: ChatGPT Export (contains mapping dict)
            elif "mapping" in conv:
                platform = default_platform or "chatgpt"
                source_agent = "gpt"
                conv_uuid = conv.get("id") or f"chatgpt_{uuid.uuid4().hex[:8]}"
                conv_id = f"conv_gpt_{conv_uuid.replace('-', '')[:12]}"
                title = conv.get("title") or "Untitled ChatGPT Conversation"
                create_time = conv.get("create_time")
                created_at = datetime.fromtimestamp(create_time, tz=timezone.utc).isoformat() if create_time else datetime.now(timezone.utc).isoformat()

                messages = []
                mapping = conv.get("mapping", {})
                for node in mapping.values():
                    msg = node.get("message")
                    if msg and msg.get("content") and msg.get("author"):
                        role = msg["author"].get("role", "user")
                        if role in ("user", "assistant", "system"):
                            parts = msg["content"].get("parts", [])
                            text_content = "\n".join(str(p) for p in parts if isinstance(p, str)).strip()
                            if text_content:
                                messages.append({"role": role, "content": text_content})

            # Format C: Standard / Generic JSON (contains messages list)
            elif "messages" in conv:
                platform = default_platform or conv.get("platform") or "custom"
                source_agent = conv.get("source_agent") or "user"
                conv_id = conv.get("id") or f"conv_{platform}_{uuid.uuid4().hex[:8]}"
                title = conv.get("title") or "Imported Conversation"
                created_at = conv.get("created_at") or datetime.now(timezone.utc).isoformat()
                messages = [
                    {"role": m.get("role", "user"), "content": m.get("content", "")}
                    for m in conv.get("messages", [])
                    if isinstance(m, dict) and m.get("content")
                ]
            else:
                continue

            if not messages:
                continue

            # Check for duplicates
            existing = session.exec(select(ConversationItem).where(ConversationItem.id == conv_id)).first()
            if existing:
                skipped_count += 1
                continue

            first_user_preview = next((m["content"][:200] for m in messages if m["role"] == "user"), "")
            summary = conv.get("summary") or (f"Topic: {title}. Preview: {first_user_preview}" if first_user_preview else f"Conversation on {platform}: {title}")
            text_for_vector = f"Platform: {platform}. Title: {title}\nSummary: {summary}\n{first_user_preview}"
            embedding = generate_embedding(text_for_vector)

            item = ConversationItem(
                id=conv_id,
                platform=platform,
                title=title,
                summary=summary,
                messages_json=json.dumps(messages),
                embedding_json=json.dumps(embedding),
                source_agent=source_agent,
                created_at=created_at
            )
            session.add(item)
            session.commit()

            if is_postgres:
                try:
                    with Session(engine) as p_sess:
                        vec_str = f"[{','.join(str(x) for x in embedding)}]"
                        p_sess.exec(text("UPDATE conversations SET embedding_vector = CAST(:vec AS vector) WHERE id = :id"), params={"vec": vec_str, "id": conv_id})
                        p_sess.commit()
                except Exception as p_err:
                    print(f"conversation batch vector note: {p_err}")

            ingested_count += 1

    return {
        "success": True,
        "ingested": ingested_count,
        "skipped": skipped_count,
        "total_processed": len(conversations) if isinstance(conversations, list) else 1,
        "message": f"Successfully imported {ingested_count} conversation(s) into database ({skipped_count} duplicate(s) skipped)."
    }

def search_conversations(
    query: str,
    platform: Optional[str] = None,
    source_agent: Optional[str] = None,
    limit: int = 5
) -> List[Dict[str, Any]]:
    """
    Semantic vector search specifically across chat conversation transcripts.
    """
    query_vector = generate_embedding(query)
    query_lower = (query or "").lower()
    query_keywords = [k for k in query_lower.split() if len(k) > 2]

    candidates: List[Dict[str, Any]] = []

    with Session(engine) as session:
        if is_postgres:
            try:
                vector_str = f"[{','.join(str(x) for x in query_vector)}]"
                sql = """
                SELECT id, platform, title, summary, source_agent, messages_json, created_at,
                       1.0 - (embedding_vector <=> CAST(:vec AS vector)) AS vector_score
                FROM conversations
                WHERE embedding_vector IS NOT NULL
                ORDER BY embedding_vector <=> CAST(:vec AS vector) ASC
                LIMIT 40;
                """
                rows = session.exec(text(sql), params={"vec": vector_str}).all()
                for r in rows:
                    if platform and r.platform.lower() != platform.lower():
                        continue
                    if source_agent and (r.source_agent or "").lower() != source_agent.lower():
                        continue
                    try:
                        msgs = json.loads(r.messages_json or "[]")
                    except Exception:
                        msgs = []
                    candidates.append({
                        "id": r.id,
                        "source": "conversation",
                        "platform": r.platform,
                        "title": r.title,
                        "summary": r.summary,
                        "source_agent": r.source_agent or "user",
                        "content": f"[{r.platform.upper()} Transcript] {r.title}: {r.summary}",
                        "messages": msgs,
                        "messages_count": len(msgs),
                        "created_at": r.created_at,
                        "score": float(r.vector_score or 0.0),
                        "vector_score": float(r.vector_score or 0.0)
                    })
            except Exception as pg_err:
                print(f"pgvector search_conversations note: {pg_err}")
                session.rollback()

        if not candidates:
            stmt = select(ConversationItem).limit(60)
            if platform:
                stmt = stmt.where(ConversationItem.platform == platform)
            if source_agent:
                stmt = stmt.where(ConversationItem.source_agent == source_agent)
            conv_items = session.exec(stmt).all()
            for c in conv_items:
                score = 0.0
                try:
                    c_vec = json.loads(c.embedding_json)
                    score += cosine_similarity(query_vector, c_vec) * 0.7
                except Exception:
                    pass
                c_text = f"{c.title} {c.summary}".lower()
                kw_hits = sum(1 for kw in query_keywords if kw in c_text)
                if query_keywords:
                    score += (kw_hits / len(query_keywords)) * 0.3

                if score > 0.05:
                    try:
                        msgs = json.loads(c.messages_json or "[]")
                    except Exception:
                        msgs = []
                    candidates.append({
                        "id": c.id,
                        "source": "conversation",
                        "platform": c.platform,
                        "title": c.title,
                        "summary": c.summary,
                        "source_agent": c.source_agent or "user",
                        "content": f"[{c.platform.upper()} Transcript] {c.title}: {c.summary}",
                        "messages": msgs,
                        "messages_count": len(msgs),
                        "created_at": c.created_at,
                        "score": round(score, 4)
                    })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    top_candidates = candidates[:30]
    reranked = rerank_candidates(query=query, candidates=top_candidates, top_n=limit)
    return reranked

def backfill_conversation_vectors() -> int:
    """Computes and backfills Gemini Embedding 2 vectors for all stored conversations."""
    count = 0
    with Session(engine) as session:
        convs = session.exec(select(ConversationItem)).all()
        for c in convs:
            msgs_preview = ""
            if c.messages_json:
                try:
                    msgs = json.loads(c.messages_json)
                    msgs_preview = "\n".join(f"{m.get('role', 'user')}: {m.get('content', '')[:100]}" for m in msgs[:4])
                except Exception:
                    pass
            text_for_vector = f"Chat Platform: {c.platform}. Title: {c.title}\nSummary: {c.summary}\n{msgs_preview}"
            emb = generate_embedding(text_for_vector)
            c.embedding_json = json.dumps(emb)
            session.add(c)
            session.commit()

            if is_postgres:
                try:
                    with Session(engine) as p_sess:
                        vec_str = f"[{','.join(str(x) for x in emb)}]"
                        p_sess.exec(text("UPDATE conversations SET embedding_vector = CAST(:vec AS vector) WHERE id = :id"), params={"vec": vec_str, "id": c.id})
                        p_sess.commit()
                except Exception as p_err:
                    print(f"backfill pgvector note: {p_err}")
            count += 1
    return count

def get_memories(page: int = 1, limit: int = 20, category: Optional[str] = None, source_agent: Optional[str] = None) -> Dict[str, Any]:
    with Session(engine) as session:
        stmt = select(MemoryItem)
        if category:
            stmt = stmt.where(MemoryItem.category == category)
        if source_agent:
            stmt = stmt.where(MemoryItem.source_agent == source_agent)

        all_items = session.exec(stmt).all()
        total = len(all_items)

        offset = (page - 1) * limit
        items = session.exec(stmt.order_by(MemoryItem.created_at.desc()).offset(offset).limit(limit)).all()

        res_memories = []
        for mem in items:
            res_memories.append({
                "id": mem.id,
                "content": mem.content,
                "category": mem.category,
                "media_type": mem.media_type,
                "media_url": mem.media_url,
                "source_agent": getattr(mem, "source_agent", "user") or "user",
                "parent_id": mem.parent_id,
                "chunk_index": mem.chunk_index,
                "total_chunks": mem.total_chunks,
                "tags": json.loads(mem.tags_json or "[]"),
                "attachments": _hydrate_attachments(getattr(mem, "attachments_json", "[]"), media_url=mem.media_url, media_type=mem.media_type),
                "created_at": mem.created_at,
                "last_accessed": mem.last_accessed
            })

        pages = (total + limit - 1) // limit if limit > 0 else 1
        return {
            "memories": res_memories,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": pages
        }

def delete_memory(memory_id: str) -> bool:
    with Session(engine) as session:
        all_to_delete = session.exec(select(MemoryItem).where((MemoryItem.id == memory_id) | (MemoryItem.parent_id == memory_id))).all()
        if not all_to_delete:
            return False

        # Extract all referenced R2 storage keys to purge
        keys_to_purge = set()
        for item in all_to_delete:
            raw_att = getattr(item, "attachments_json", "[]")
            if raw_att:
                try:
                    parsed = json.loads(raw_att)
                    for a in parsed:
                        if isinstance(a, dict):
                            k = a.get("key")
                            if k and not k.startswith("http"):
                                keys_to_purge.add(k)
                except Exception:
                    pass
            session.delete(item)
        # Cascade delete from Cloudflare R2 and purge vectorized chunks
        if keys_to_purge:
            for k in keys_to_purge:
                try:
                    delete_storage_file_index(k)
                except Exception:
                    pass
            if storage_service.is_enabled():
                try:
                    storage_service.delete_files(list(keys_to_purge))
                except Exception as e:
                    print(f"R2 cascading cleanup note: {e}")

        return True

def reset_all_memories() -> int:
    with Session(engine) as session:
        all_mems = session.exec(select(MemoryItem)).all()
        count = len(all_mems)
        keys_to_purge = set()
        for mem in all_mems:
            raw_att = getattr(mem, "attachments_json", "[]")
            if raw_att:
                try:
                    parsed = json.loads(raw_att)
                    for a in parsed:
                        if isinstance(a, dict):
                            k = a.get("key")
                            if k and not k.startswith("http"):
                                keys_to_purge.add(k)
                except Exception:
                    pass
            session.delete(mem)
        # Cascade batch delete from Cloudflare R2 and purge all storage chunks
        try:
            delete_all_storage_file_indexes()
        except Exception:
            pass

        if keys_to_purge and storage_service.is_enabled():
            try:
                storage_service.delete_files(list(keys_to_purge))
            except Exception as e:
                print(f"R2 cascading purge note: {e}")

        return count

def export_all_memories() -> List[Dict[str, Any]]:
    with Session(engine) as session:
        mems = session.exec(select(MemoryItem).order_by(MemoryItem.created_at.desc())).all()
        return [{
            "id": m.id,
            "content": m.content,
            "category": m.category,
            "media_type": m.media_type,
            "media_url": m.media_url,
            "source_agent": getattr(m, "source_agent", "user") or "user",
            "parent_id": m.parent_id,
            "chunk_index": m.chunk_index,
            "total_chunks": m.total_chunks,
            "tags": json.loads(m.tags_json or "[]"),
            "attachments": _hydrate_attachments(getattr(m, "attachments_json", "[]"), media_url=m.media_url, media_type=m.media_type),
            "created_at": m.created_at,
            "last_accessed": m.last_accessed
        } for m in mems]

def update_memory(
    memory_id: str,
    content: Optional[str] = None,
    category: Optional[str] = None,
    source_agent: Optional[str] = None,
    tags: Optional[List[str]] = None,
    attachments: Optional[List[Dict[str, Any]]] = None
) -> Optional[Dict[str, Any]]:
    with Session(engine) as session:
        item = session.exec(select(MemoryItem).where(MemoryItem.id == memory_id)).first()
        if not item:
            return None

        if content is not None:
            item.content = content
            item.embedding_json = json.dumps(generate_embedding(content))
        if category is not None:
            item.category = category
        if source_agent is not None:
            item.source_agent = source_agent
        if tags is not None:
            item.tags_json = json.dumps(tags)
        if attachments is not None:
            item.attachments_json = json.dumps(attachments)
            # Also update child chunks if this is a parent memory
            child_chunks = session.exec(select(MemoryItem).where(MemoryItem.parent_id == memory_id)).all()
            for chk in child_chunks:
                chk.attachments_json = json.dumps(attachments)

        now_str = datetime.now(timezone.utc).isoformat()
        item.last_accessed = now_str
        session.commit()

        return {
            "id": item.id,
            "content": item.content,
            "category": item.category,
            "media_type": item.media_type,
            "media_url": item.media_url,
            "source_agent": getattr(item, "source_agent", "user") or "user",
            "parent_id": item.parent_id,
            "chunk_index": item.chunk_index,
            "total_chunks": item.total_chunks,
            "tags": json.loads(item.tags_json or "[]"),
            "attachments": _hydrate_attachments(getattr(item, "attachments_json", "[]"), media_url=item.media_url, media_type=item.media_type),
            "created_at": item.created_at,
            "last_accessed": item.last_accessed
        }

def get_conversations(page: int = 1, limit: int = 20, platform: Optional[str] = None, source_agent: Optional[str] = None) -> Dict[str, Any]:
    with Session(engine) as session:
        stmt = select(ConversationItem)
        if platform:
            stmt = stmt.where(ConversationItem.platform == platform)
        if source_agent:
            stmt = stmt.where(ConversationItem.source_agent == source_agent)

        all_items = session.exec(stmt).all()
        total = len(all_items)

        offset = (page - 1) * limit
        items = session.exec(stmt.order_by(ConversationItem.created_at.desc()).offset(offset).limit(limit)).all()

        res_convs = []
        vectorized_count = 0
        for conv in items:
            has_vec = bool(conv.embedding_json and conv.embedding_json != "[]")
            if has_vec:
                vectorized_count += 1
            res_convs.append({
                "id": conv.id,
                "platform": conv.platform,
                "title": conv.title,
                "summary": conv.summary,
                "source_agent": getattr(conv, "source_agent", "user") or "user",
                "messages": json.loads(conv.messages_json or "[]"),
                "is_vectorized": has_vec,
                "created_at": conv.created_at
            })

        pages = (total + limit - 1) // limit if limit > 0 else 1
        total_vectorized = sum(1 for c in all_items if c.embedding_json and c.embedding_json != "[]")
        return {
            "conversations": res_convs,
            "total": total,
            "total_vectorized": total_vectorized,
            "page": page,
            "limit": limit,
            "pages": pages
        }

def delete_conversation(conv_id: str) -> bool:
    """Deletes a conversation transcript session by ID."""
    with Session(engine) as session:
        conv = session.exec(select(ConversationItem).where(ConversationItem.id == conv_id)).first()
        if not conv:
            return False
        session.delete(conv)
        session.commit()
        return True

def vectorize_conversation(conv_id: str) -> bool:
    """Generates Gemini Embedding 2 vector for a single conversation."""
    with Session(engine) as session:
        c = session.exec(select(ConversationItem).where(ConversationItem.id == conv_id)).first()
        if not c:
            return False
        msgs_preview = ""
        if c.messages_json:
            try:
                msgs = json.loads(c.messages_json)
                msgs_preview = "\n".join(f"{m.get('role', 'user')}: {m.get('content', '')[:100]}" for m in msgs[:4])
            except Exception:
                pass
        text_for_vector = f"Chat Platform: {c.platform}. Title: {c.title}\nSummary: {c.summary}\n{msgs_preview}"
        emb = generate_embedding(text_for_vector)
        c.embedding_json = json.dumps(emb)
        session.add(c)
        session.commit()

        if is_postgres:
            try:
                with Session(engine) as p_sess:
                    vec_str = f"[{','.join(str(x) for x in emb)}]"
                    p_sess.exec(text("UPDATE conversations SET embedding_vector = CAST(:vec AS vector) WHERE id = :id"), params={"vec": vec_str, "id": c.id})
                    p_sess.commit()
            except Exception as p_err:
                print(f"vectorize conv pgvector note: {p_err}")
        return True
def delete_profile_rule(rule_id: str) -> bool:
    with Session(engine) as session:
        item = session.exec(select(ProfileItem).where((ProfileItem.id == rule_id) | (ProfileItem.key == rule_id))).first()
        if not item:
            return False
        session.delete(item)
        session.commit()
        return True

def get_stats() -> Dict[str, Any]:
    with Session(engine) as session:
        memories = session.exec(select(MemoryItem)).all()
        profile_rules = session.exec(select(ProfileItem)).all()
        chat_logs = session.exec(select(ConversationItem)).all()
        task_sessions = session.exec(select(TaskSessionItem)).all()
        storage_files = session.exec(select(StorageFileItem)).all()
        storage_chunks = session.exec(select(StorageChunkItem)).all()

        source_distribution = {}
        for mem in memories:
            agent = getattr(mem, "source_agent", "user") or "user"
            source_distribution[agent] = source_distribution.get(agent, 0) + 1

        return {
            "total_memories": len(memories),
            "total_profile_rules": len(profile_rules),
            "total_chat_logs": len(chat_logs),
            "total_task_sessions": len(task_sessions),
            "total_storage_files": len(storage_files),
            "total_storage_chunks": len(storage_chunks),
            "source_distribution": source_distribution
        }
