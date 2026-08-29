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
from gigamind.services.indexing import delete_storage_file_index, delete_all_storage_file_indexes


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
    query: str,
    category: Optional[str] = None,
    source_agent: Optional[str] = None,
    limit: int = 5,
    scope: str = "all"
) -> List[Dict[str, Any]]:
    """
    Unified 2-Stage RAG Search Engine:
    - scope: "all" (searches memories, profile rules & vectorized R2 files),
             "memories" (searches textual memories only),
             "files" (searches vectorized file storage chunks only).
    - Stage 1: Vector Candidate Retrieval (Top 30 from memories, Top 30 from file storage).
    - Stage 2: Cross-Encoder Neural Rerank Pass (Top limit items returned across all knowledge).
    """
    scope_clean = (scope or "all").lower().strip()
    if scope_clean not in ("all", "memories", "files"):
        scope_clean = "all"

    query_vector = generate_embedding(query)
    query_lower = (query or "").lower()
    query_keywords = [k for k in re_words if len(k) > 2] if (re_words := query_lower.split()) else []

    candidates: List[Dict[str, Any]] = []

    with Session(engine) as session:
        # ====================================================
        # 1. MEMORIES & PROFILE RULES SCAN (if scope: all | memories)
        # ====================================================
        if scope_clean in ("all", "memories"):
            if is_postgres:
                try:
                    vector_str = f"[{','.join(str(x) for x in query_vector)}]"
                    sql = """
                    SELECT id, content, category, media_type, media_url, source_agent, tags_json, attachments_json, parent_id, chunk_index, total_chunks,
                           1.0 - (embedding_vector <=> CAST(:vec AS vector)) AS vector_score
                    FROM memories
                    WHERE (:cat IS NULL OR category = :cat)
                      AND (:agent IS NULL OR source_agent = :agent)
                      AND embedding_vector IS NOT NULL
                    ORDER BY embedding_vector <=> CAST(:vec AS vector) ASC
                    LIMIT 30;
                    """
                    params = {"vec": vector_str, "cat": category, "agent": source_agent}
                    rows = session.exec(text(sql), params=params).all()

                    for row in rows:
                        att_raw = getattr(row, "attachments_json", "[]")
                        m_url = getattr(row, "media_url", None)
                        m_type = getattr(row, "media_type", None)
                        hydrated_atts = _hydrate_attachments(att_raw, media_url=m_url, media_type=m_type)

                        c_dict = {
                            "id": row.id,
                            "source": "memory",
                            "content": row.content,
                            "category": row.category,
                            "source_agent": row.source_agent or "user",
                            "score": float(row.vector_score or 0.0),
                            "tags": json.loads(row.tags_json or "[]"),
                            "attachments": hydrated_atts,
                            "parent_id": row.parent_id,
                            "chunk_index": row.chunk_index,
                            "total_chunks": row.total_chunks
                        }
                        candidates.append(c_dict)
                except Exception as pg_err:
                    print(f"pgvector memories query fallback: {pg_err}")
                    session.rollback()

            # Fallback / SQLite Candidate Scanner for memories
            if not any(c.get("source") == "memory" for c in candidates):
                stmt = select(MemoryItem)
                if category:
                    stmt = stmt.where(MemoryItem.category == category)
                if source_agent:
                    stmt = stmt.where(MemoryItem.source_agent == source_agent)

                stmt = stmt.order_by(MemoryItem.created_at.desc()).limit(100)
                memories = session.exec(stmt).all()
                now_str = datetime.now(timezone.utc).isoformat()

                for mem in memories:
                    score = 0.0
                    try:
                        vec = json.loads(mem.embedding_json)
                        score += cosine_similarity(query_vector, vec) * 0.7
                    except Exception:
                        pass

                    content_lower = mem.content.lower()
                    kw_hits = sum(1 for kw in query_keywords if kw in content_lower)
                    if query_keywords:
                        score += (kw_hits / len(query_keywords)) * 0.3

                    if score > 0.05:
                        candidates.append({
                            "id": mem.id,
                            "source": "memory",
                            "content": mem.content,
                            "category": mem.category,
                            "source_agent": getattr(mem, "source_agent", "user") or "user",
                            "score": round(score, 4),
                            "tags": json.loads(mem.tags_json or "[]"),
                            "attachments": _hydrate_attachments(getattr(mem, "attachments_json", "[]"), media_url=mem.media_url, media_type=mem.media_type),
                            "parent_id": mem.parent_id,
                            "chunk_index": mem.chunk_index,
                            "total_chunks": mem.total_chunks
                        })
                        mem.last_accessed = now_str

                session.commit()

            # Search Profile Rules
            profile_stmt = select(ProfileItem)
            if category:
                profile_stmt = profile_stmt.where(ProfileItem.category == category)
            if source_agent:
                profile_stmt = profile_stmt.where(ProfileItem.source_agent == source_agent)

            profiles = session.exec(profile_stmt).all()
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
            file_candidates: List[Dict[str, Any]] = []
            if is_postgres:
                try:
                    vector_str = f"[{','.join(str(x) for x in query_vector)}]"
                    sql_files = """
                    SELECT id, file_id, file_key, filename, chunk_index, total_chunks, page_number, content,
                           1.0 - (embedding_vector <=> CAST(:vec AS vector)) AS vector_score
                    FROM storage_chunks
                    WHERE embedding_vector IS NOT NULL
                    ORDER BY embedding_vector <=> CAST(:vec AS vector) ASC
                    LIMIT 30;
                    """
                    rows_files = session.exec(text(sql_files), params={"vec": vector_str}).all()
                    for rf in rows_files:
                        url = None
                        if storage_service.is_enabled():
                            url = storage_service.get_presigned_download_url(rf.file_key, filename=rf.filename)

                        file_candidates.append({
                            "id": rf.id,
                            "source": "file",
                            "content": rf.content,
                            "filename": rf.filename,
                            "file_key": rf.file_key,
                            "file_id": rf.file_id,
                            "page_number": rf.page_number,
                            "chunk_index": rf.chunk_index,
                            "total_chunks": rf.total_chunks,
                            "score": float(rf.vector_score or 0.0),
                            "url": url or "",
                            "category": "file"
                        })
                except Exception as pg_f_err:
                    print(f"pgvector storage_chunks query note: {pg_f_err}")
                    session.rollback()

            # Fallback SQLite candidate scanner for storage chunks
            if not file_candidates:
                f_chunks = session.exec(select(StorageChunkItem).limit(100)).all()
                for fc in f_chunks:
                    f_score = 0.0
                    try:
                        fc_vec = json.loads(fc.embedding_json)
                        f_score += cosine_similarity(query_vector, fc_vec) * 0.7
                    except Exception:
                        pass

                    fc_lower = fc.content.lower()
                    kw_hits = sum(1 for kw in query_keywords if kw in fc_lower)
                    if query_keywords:
                        f_score += (kw_hits / len(query_keywords)) * 0.3

                    if f_score > 0.05:
                        url = None
                        if storage_service.is_enabled():
                            url = storage_service.get_presigned_download_url(fc.file_key, filename=fc.filename)

                        file_candidates.append({
                            "id": fc.id,
                            "source": "file",
                            "content": fc.content,
                            "filename": fc.filename,
                            "file_key": fc.file_key,
                            "file_id": fc.file_id,
                            "page_number": fc.page_number,
                            "chunk_index": fc.chunk_index,
                            "total_chunks": fc.total_chunks,
                            "score": round(f_score, 4),
                            "url": url or "",
                            "category": "file"
                        })

            candidates.extend(file_candidates)

    # Sort all candidates by initial score
    candidates.sort(key=lambda x: x["score"], reverse=True)
    top_candidates = candidates[:50]

    # ====================================================
    # STAGE 2: CROSS-ENCODER NEURAL RERANK PASS
    # ====================================================
    reranked_results = rerank_candidates(query=query, candidates=top_candidates, top_n=limit)

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
                "page_number": item.get("page_number"),
                "chunk_index": item.get("chunk_index", 0),
                "total_chunks": item.get("total_chunks", 1),
                "score": item["score"],
                "vector_score": item.get("vector_score", item["score"]),
                "rerank_score": item.get("rerank_score", item["score"]),
                "url": item.get("url", "")
            }
            if item.get("page_number") is not None:
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
    text_for_vector = f"{title} {summary}"
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

    return {
        "id": conv_id,
        "platform": platform,
        "title": title,
        "summary": summary,
        "source_agent": source_agent or "user",
        "created_at": now_str
    }

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
        for conv in items:
            res_convs.append({
                "id": conv.id,
                "platform": conv.platform,
                "title": conv.title,
                "summary": conv.summary,
                "source_agent": getattr(conv, "source_agent", "user") or "user",
                "messages": json.loads(conv.messages_json or "[]"),
                "created_at": conv.created_at
            })

        pages = (total + limit - 1) // limit if limit > 0 else 1
        return {
            "conversations": res_convs,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": pages
        }

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

        source_distribution = {}
        for mem in memories:
            agent = getattr(mem, "source_agent", "user") or "user"
            source_distribution[agent] = source_distribution.get(agent, 0) + 1

        return {
            "total_memories": len(memories),
            "total_profile_rules": len(profile_rules),
            "total_chat_logs": len(chat_logs),
            "total_task_sessions": len(task_sessions),
            "source_distribution": source_distribution
        }
