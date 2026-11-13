import json
import math
import re
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from sqlmodel import Session, select, text
from sqlalchemy import func, update, delete
from gigamind.db.database import engine, is_postgres, ProfileItem, MemoryItem, ConversationItem, TaskSessionItem, StorageFileItem, StorageChunkItem
from gigamind.services.embedding import generate_embedding, cosine_similarity
from gigamind.services import embedding as embedding_config
from gigamind.services import file_lifecycle
from gigamind.services.file_retrieval import file_candidates
from gigamind.db.jobs import ResourceJobState  # Register job models before metadata initialization.
from gigamind.db.memory_index import MemoryIndexState
from fastapi import HTTPException
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
    """Retrieve legacy sources with bounded lexical/vector pools and reranking.

    File evidence is deduplicated by storage key after ranking. Accepted knowledge
    uses its separate scoped service and does not pass through this pipeline.
    """
    scope_clean = (scope or "all").lower().strip()
    if scope_clean not in ("all", "memories", "files"):
        scope_clean = "all"

    query_vector = None
    try:
        vector = generate_embedding(text=query if query else None, image_base64=query_image_base64)
        query_vector = embedding_config.validate_embedding_vector(vector)
    except embedding_config.EmbeddingUnavailable:
        if query_image_base64:
            raise HTTPException(503, "Image search requires an available embedding provider") from None
    except embedding_config.EmbeddingInputError:
        raise HTTPException(422, "Search input is empty, oversized or unsupported") from None

    query_keywords = list(dict.fromkeys(re.findall(r"\w+", (query or "").casefold())))

    def lexical_hits(content):
        folded = content.casefold()
        return sum(
            bool(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", folded))
            if len(term) <= 2 and term.isascii() else term in folded
            for term in query_keywords
        )

    candidates: List[Dict[str, Any]] = []

    with Session(engine) as session:
        # ====================================================
        # 1. MEMORIES & PROFILE RULES SCAN (if scope: all | memories)
        # ====================================================
        if scope_clean in ("all", "memories"):
            raw_mem_candidates: List[Dict[str, Any]] = []
            if is_postgres and query_vector is not None:
                vector_str = f"[{','.join(str(x) for x in query_vector)}]"
                sql = """
                SELECT id, content, category, source_agent, parent_id, chunk_index, total_chunks, tags_json, attachments_json,
                       1.0 - (embedding_vector <=> CAST(:vec AS vector)) AS vector_score
                FROM memories
                WHERE embedding_vector IS NOT NULL
                  AND (:category IS NULL OR category = :category)
                  AND (:source_agent IS NULL OR source_agent = :source_agent)
                ORDER BY embedding_vector <=> CAST(:vec AS vector) ASC
                LIMIT 40;
                """
                rows = session.exec(text(sql), params={"vec": vector_str, "category": category, "source_agent": source_agent}).all()
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
                        "vector_score": float(r.vector_score or 0.0),
                        "retrieval_method": "vector"
                    })

            # Keyword scan for memories
            mem_stmt = select(MemoryItem)
            if category:
                mem_stmt = mem_stmt.where(MemoryItem.category == category)
            if source_agent:
                mem_stmt = mem_stmt.where(MemoryItem.source_agent == source_agent)
            keyword_memories = session.exec(mem_stmt).all()
            for mem in keyword_memories:
                kw_score = 0.0
                kw_hits = lexical_hits(mem.content)
                if query_keywords:
                    kw_score = (kw_hits / len(query_keywords)) * 0.4

                if kw_score > 0:
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
                        "score": round(kw_score, 4),
                        "retrieval_method": "lexical"
                    })

            # Deduplicate memory chunks by parent memory
            distinct_mem_map: Dict[str, Dict[str, Any]] = {}
            for mc in raw_mem_candidates:
                pkey = mc.get("parent_id") or mc.get("id")
                previous = distinct_mem_map.get(pkey)
                if previous is None or (-mc["score"], str(mc["id"])) < (-previous["score"], str(previous["id"])):
                    distinct_mem_map[pkey] = mc

            candidates.extend(distinct_mem_map.values())

            # Profile rules scan
            profile_stmt = select(ProfileItem)
            if category:
                profile_stmt = profile_stmt.where(ProfileItem.category == category)
            if source_agent:
                profile_stmt = profile_stmt.where(ProfileItem.source_agent == source_agent)
            profiles = session.exec(profile_stmt).all()
            for prof in profiles:
                p_score = lexical_hits(f"{prof.key}: {prof.value}") * 0.4

                if p_score > 0:
                    candidates.append({
                        "id": prof.id,
                        "source": "profile",
                        "content": f"[PROFILE RULE] {prof.key} = {prof.value}",
                        "category": prof.category,
                        "source_agent": getattr(prof, "source_agent", "user") or "user",
                        "score": round(p_score, 4),
                        "retrieval_method": "lexical"
                    })
        if scope_clean in ("all", "files"):
            lexical, vectors = file_candidates(
                session, query_vector=query_vector, lexical_hits=lexical_hits,
                term_count=len(query_keywords), source_agent=source_agent, category=category,
                capacity=max(25, limit), is_postgres=is_postgres,
            )
            candidates.extend(lexical)
            candidates.extend(vectors)

    # Reserve space for each retrieval method before comparing/reranking raw scores.
    capacity = max(25, limit)
    order = lambda item: (-item["score"], str(item.get("source", "")), str(item["id"]))
    lexical = sorted((c for c in candidates if c["retrieval_method"] == "lexical"), key=order)[:capacity]
    vectors = sorted((c for c in candidates if c["retrieval_method"] != "lexical"), key=order)[:capacity]
    def candidate_identity(item):
        return (item["source"], item.get("file_key"), item.get("_record_type"), item["id"])

    selected = {}
    for candidate in lexical + vectors:
        key = candidate_identity(candidate)
        if key in selected:
            previous = selected[key]
            combined = {**previous, **candidate, "retrieval_method": "lexical+vector"}
            combined["score"] = max(previous["score"], candidate["score"])
            combined["matching_pages"] = sorted(set(previous.get("matching_pages", []) + candidate.get("matching_pages", [])))[:8]
            selected[key] = combined
        else:
            selected[key] = candidate
    candidates = list(selected.values())
    admitted = []
    urls = {}
    for candidate in candidates:
        if candidate.get("source") == "file":
            try:
                with file_lifecycle.active_access(candidate["file_key"], engine):
                    key = candidate["file_key"]
                    if key not in urls:
                        urls[key] = storage_service.get_presigned_download_url(
                            key, filename=candidate.get("filename")
                        ) or "" if storage_service.is_enabled() else ""
                    candidate["url"] = urls[key]
            except HTTPException as exc:
                if exc.status_code == 409:
                    continue
                raise
        admitted.append(candidate)
    candidates = admitted
    # Sort all candidates by initial score
    candidates.sort(key=lambda x: (-x["score"], str(x.get("source", "")), str(x["id"])))
    top_candidates = candidates

    # ====================================================
    # STAGE 2: CROSS-ENCODER NEURAL RERANK PASS
    # ====================================================
    original_scores = {candidate_identity(c): c.get("vector_score") for c in top_candidates}
    reranked_results = rerank_candidates(query=query or "visual and multimodal search", candidates=top_candidates, top_n=len(top_candidates))

    final_output = []
    seen = set()
    for item in reranked_results:
        src = item.get("source", "memory")
        identity = (src, item.get("file_key") if src == "file" else item["id"])
        if identity in seen:
            continue
        seen.add(identity)
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
                "url": item.get("url", ""),
                "category": "file",
                "matching_pages": item.get("matching_pages", []),
            }
            if item.get("source_agent") is not None:
                res_item["source_agent"] = item["source_agent"]
            if "is_visual_anchor" in item:
                res_item["is_visual_anchor"] = item["is_visual_anchor"]
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

        method = item.get("retrieval_method", "vector")
        res_item["retrieval_method"] = method
        actual_vector_score = original_scores.get(candidate_identity(item))
        if actual_vector_score is None:
            res_item.pop("vector_score", None)
        else:
            res_item["vector_score"] = actual_vector_score
        final_output.append(res_item)
        if len(final_output) >= limit:
            break

    return final_output

def _now():
    return datetime.now(timezone.utc).isoformat()


def _memory_response(item, state):
    return {
        "id": item.id,
        "content": item.content,
        "category": item.category,
        "media_type": item.media_type,
        "media_url": item.media_url,
        "source_agent": item.source_agent or "user",
        "parent_id": item.parent_id,
        "chunk_index": item.chunk_index,
        "total_chunks": item.total_chunks,
        "tags": json.loads(item.tags_json or "[]"),
        "attachments": _hydrate_attachments(
            item.attachments_json, item.media_url, item.media_type
        ),
        "created_at": item.created_at,
        "last_accessed": item.last_accessed,
        "revision": state.revision if state else None,
        "index_status": state.index_status if state else "pending",
        "index_error": state.index_error if state else None,
        "indexed_revision": state.indexed_revision if state else None,
        "embedding_model": state.embedding_model if state else None,
        "embedding_dimension": state.embedding_dimension if state else None,
    }


def _index_memory(memory_id, revision, content):
    try:
        chunks = chunk_text(
            content, chunk_size=500, chunk_overlap=100, min_threshold=600
        )
        parts = [c["content"] for c in chunks] if len(chunks) > 1 else [content]
        model, dimension = embedding_config.MODEL_NAME, embedding_config.DEFAULT_DIM
        if (
            not isinstance(model, str)
            or not model.strip()
            or not isinstance(dimension, int)
            or dimension <= 0
        ):
            raise ValueError("Invalid embedding configuration")
        vectors = []
        for part in parts:
            vector = generate_embedding(part)
            if len(vector) != dimension or any(
                isinstance(v, bool)
                or not isinstance(v, (int, float))
                or not math.isfinite(v)
                for v in vector
            ):
                raise ValueError("Invalid embedding vector")
            vectors.append(vector)
        with Session(engine) as session:
            # This conditional write locks the state row until vectors and completion commit.
            result = session.exec(
                update(MemoryIndexState)
                .where(
                    MemoryIndexState.memory_id == memory_id,
                    MemoryIndexState.revision == revision,
                )
                .values(updated_at=_now())
            )
            if result.rowcount != 1:
                session.rollback()
                return
            item = session.get(MemoryItem, memory_id)
            if item is None:
                session.rollback()
                return
            session.exec(delete(MemoryItem).where(MemoryItem.parent_id == memory_id))
            item.embedding_json = "[]"
            if is_postgres:
                session.exec(
                    text("UPDATE memories SET embedding_vector = NULL WHERE id = :id"),
                    params={"id": memory_id},
                )
            targets = []
            if len(chunks) > 1:
                item.total_chunks = len(chunks)
                for chunk, vector in zip(chunks, vectors):
                    child = MemoryItem(
                        id=f"{memory_id}_chk_{chunk['chunk_index']}",
                        content=chunk["content"],
                        category=item.category,
                        media_type=item.media_type,
                        media_url=item.media_url,
                        source_agent=item.source_agent,
                        tags_json=item.tags_json,
                        attachments_json=item.attachments_json,
                        embedding_json=json.dumps(vector),
                        parent_id=memory_id,
                        chunk_index=chunk["chunk_index"],
                        total_chunks=len(chunks),
                        created_at=item.created_at,
                        last_accessed=item.last_accessed,
                    )
                    session.add(child)
                    targets.append((child.id, vector))
            else:
                item.embedding_json = json.dumps(vectors[0])
                targets.append((item.id, vectors[0]))
            session.add(item)
            session.flush()
            if is_postgres:
                for target_id, vector in targets:
                    session.exec(
                        text(
                            "UPDATE memories SET embedding_vector = CAST(:vec AS vector) WHERE id = :id"
                        ),
                        params={"vec": json.dumps(vector), "id": target_id},
                    )
            session.exec(
                update(MemoryIndexState)
                .where(MemoryIndexState.memory_id == memory_id)
                .values(
                    index_status="completed",
                    index_error=None,
                    indexed_revision=revision,
                    embedding_model=model,
                    embedding_dimension=dimension,
                    updated_at=_now(),
                )
            )
            session.commit()
    except Exception:
        with Session(engine) as session:
            session.exec(
                update(MemoryIndexState)
                .where(
                    MemoryIndexState.memory_id == memory_id,
                    MemoryIndexState.revision == revision,
                    MemoryIndexState.index_status != "completed",
                )
                .values(
                    index_status="failed",
                    index_error="Embedding failed. Check provider configuration and retry.",
                    updated_at=_now(),
                )
            )
            session.commit()


def _register_attachment_metadata(session, attachments, source_agent, timestamp):
    from gigamind.services.jobs import (
        lock_resource,
        stamp,
        utcnow,
        validate_resource_key,
    )
    from gigamind.services.file_lifecycle import owned_key

    keys = sorted(
        {
            a.get("key")
            for a in attachments
            if isinstance(a, dict) and owned_key(a.get("key"))
        }
    )
    for key in keys:
        try:
            validate_resource_key(key)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        if lock_resource(session, key, stamp(utcnow())).deleted:
            raise HTTPException(409, "Resource has been forgotten")
    for attachment in attachments:
        key = attachment.get("key")
        if not owned_key(key):
            continue
        session.exec(
            text("""INSERT INTO storage_files
            (id, key, filename, mime_type, multimodal_type, size_bytes, source_agent,
             extracted_text_length, total_chunks, indexing_status, embedding_json, created_at, updated_at)
            VALUES (:id, :key, :filename, :mime_type, 'text', :size, :source_agent,
                    0, 0, 'pending', '[]', :created_at, :updated_at)
            ON CONFLICT (key) DO NOTHING"""),
            params={
                "id": f"file_{uuid.uuid4().hex}",
                "key": key,
                "filename": attachment.get("filename")
                or key.split("/")[-1]
                or "attachment",
                "mime_type": attachment.get("mime_type") or "application/octet-stream",
                "size": attachment.get("size_bytes", 0),
                "source_agent": source_agent or "user",
                "created_at": timestamp,
                "updated_at": timestamp,
            },
        )


def add_memory(
    content: str,
    category: str = "general",
    source_agent: str = "user",
    tags: Optional[List[str]] = None,
    attachments: Optional[List[Dict[str, Any]]] = None,
    file_keys: Optional[List[str]] = None,
    media_url: Optional[str] = None,
    media_type: Optional[str] = None,
) -> Dict[str, Any]:
    if not isinstance(content, str) or not content.strip() or len(content) > 50000:
        raise HTTPException(422, "Memory content must contain 1 to 50000 characters")
    now = _now()
    memory_id = f"mem_{uuid.uuid4().hex[:12]}"
    resolved = list(attachments or [])
    for key in file_keys or []:
        if key and isinstance(key, str):
            resolved.append(
                {
                    "key": key,
                    "filename": key.split("/")[-1],
                    "mime_type": "application/octet-stream",
                    "size_bytes": 0,
                    "created_at": now,
                }
            )
    if media_url and not resolved:
        resolved.append(
            {
                "key": media_url,
                "filename": media_url.split("/")[-1] or "attachment",
                "mime_type": media_type or "application/octet-stream",
                "size_bytes": 0,
                "created_at": now,
            }
        )
    with Session(engine) as session:
        session.add(
            MemoryItem(
                id=memory_id,
                content=content,
                category=category,
                source_agent=source_agent or "user",
                media_type=media_type or "text",
                media_url=media_url,
                tags_json=json.dumps(tags or []),
                attachments_json=json.dumps(resolved),
                created_at=now,
                last_accessed=now,
            )
        )
        session.add(
            MemoryIndexState(memory_id=memory_id, created_at=now, updated_at=now)
        )
        _register_attachment_metadata(session, resolved, source_agent, now)
        session.commit()
    _index_memory(memory_id, 1, content)
    with Session(engine) as session:
        item = session.get(MemoryItem, memory_id)
        if not item:
            raise HTTPException(409, "Memory was deleted while indexing")
        response = _memory_response(item, session.get(MemoryIndexState, memory_id))
        response["chunks_created"] = item.total_chunks or 1
        return response


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

def import_conversations_data(
    raw_data: Any,
    default_platform: Optional[str] = None,
    *,
    actor=None,
    provenance: str = "unattributed",
) -> Dict[str, Any]:
    from gigamind.services.conversation_ledger import import_sources

    return import_sources(
        raw_data, default_platform, actor=actor, provenance=provenance, engine=engine
    )


def search_conversations(
    query: str,
    platform: Optional[str] = None,
    source_agent: Optional[str] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Search complete legacy transcripts, with optional existing vector candidates."""
    import re

    if not isinstance(query, str) or len(query) > 2048:
        raise HTTPException(422, "Query must be text with at most 2048 characters")
    query = query.strip()
    stop_words = {
        "a",
        "an",
        "the",
        "and",
        "or",
        "is",
        "are",
        "was",
        "were",
        "to",
        "of",
        "in",
        "on",
        "for",
        "from",
        "what",
        "which",
        "when",
        "where",
        "how",
        "why",
        "do",
        "does",
        "did",
        "i",
        "my",
        "you",
        "your",
        "me",
        "about",
    }
    terms = list(
        dict.fromkeys(
            term
            for term in re.findall(r"\w+", query.casefold())
            if term not in stop_words
        )
    )
    if not terms:
        return []
    try:
        limit = max(1, min(int(limit), 100))
    except (TypeError, ValueError, OverflowError):
        limit = 5

    def finite_number(value):
        try:
            return (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
            )
        except OverflowError:
            return False

    def unit_vector(value):
        try:
            if not (
                isinstance(value, list)
                and len(value) == embedding_config.DEFAULT_DIM
                and value
                and all(finite_number(x) for x in value)
            ):
                return None
            norm = math.hypot(*value)
            if not norm or not math.isfinite(norm):
                return None
            return [component / norm for component in value]
        except (OverflowError, ValueError):
            return None

    try:
        vector = generate_embedding(query)
    except Exception:
        vector = None
    vector = unit_vector(vector)

    with Session(engine) as session:
        native_scores = {}
        if is_postgres and vector:
            sql = text("""
                SELECT id, 1.0 - (embedding_vector <=> CAST(:vec AS vector)) AS score
                FROM conversations
                WHERE embedding_vector IS NOT NULL
                  AND (:platform IS NULL OR lower(platform) = lower(:platform))
                  AND (:source_agent IS NULL OR lower(source_agent) = lower(:source_agent))
                ORDER BY embedding_vector <=> CAST(:vec AS vector), id
                LIMIT :candidate_limit
            """)
            rows = session.exec(
                sql,
                params={
                    "vec": str(vector),
                    "platform": platform,
                    "source_agent": source_agent,
                    "candidate_limit": max(40, limit),
                },
            ).all()
            native_scores = {
                row.id: float(row.score)
                for row in rows
                if row.score is not None and math.isfinite(row.score)
            }

        stmt = select(ConversationItem)
        if platform:
            stmt = stmt.where(func.lower(ConversationItem.platform) == platform.lower())
        if source_agent:
            stmt = stmt.where(
                func.lower(ConversationItem.source_agent) == source_agent.lower()
            )
        stmt = stmt.order_by(ConversationItem.id).execution_options(yield_per=20)
        best = []
        for c in session.exec(stmt):
            try:
                messages = json.loads(c.messages_json or "[]")
            except (ValueError, TypeError):
                messages = []
            if not isinstance(messages, list):
                messages = []
            hits = set()
            snippets = []
            for field in (c.title or "", c.summary or ""):
                folded = field.casefold()
                hits.update(term for term in terms if term in folded)
            for index, message in enumerate(messages):
                if not isinstance(message, dict) or not isinstance(
                    message.get("content"), str
                ):
                    continue
                content = message["content"]
                folded = content.casefold()
                found = [term for term in terms if term in folded]
                hits.update(found)
                if found and len(snippets) < 3:
                    pos = folded.find(found[0])
                    if len(folded) != len(content):
                        folded_offset = 0
                        for original_index, char in enumerate(content):
                            folded_offset += len(char.casefold())
                            if folded_offset > pos:
                                pos = original_index
                                break
                    role = message.get("role")
                    snippet = {
                        "role": role
                        if isinstance(role, str) and len(role) <= 128
                        else "unknown",
                        "index": index,
                        "text": content[max(0, pos - 100) : pos + 200],
                    }
                    for key in ("id", "created_at"):
                        value = message.get(key)
                        if (
                            key == "id"
                            and isinstance(value, str)
                            and len(value) <= 4096
                        ) or (
                            key == "created_at"
                            and (
                                isinstance(value, str)
                                and len(value) <= 128
                                or finite_number(value)
                            )
                        ):
                            snippet[key] = message[key]
                    snippets.append(snippet)
            lexical = len(hits) / len(terms)
            semantic = native_scores.get(c.id)
            if not is_postgres and vector:
                try:
                    stored = json.loads(c.embedding_json or "[]")
                except (ValueError, TypeError):
                    stored = None
                stored = unit_vector(stored)
                if stored:
                    semantic = cosine_similarity(vector, stored)
            if not lexical and (semantic is None or semantic <= 0):
                continue
            score = (0.5 + lexical * 0.25 if lexical else 0) + (
                min(1.0, max(0.0, semantic)) * 0.25 if semantic is not None else 0
            )
            result = {
                "id": c.id,
                "source": "conversation",
                "platform": c.platform,
                "title": c.title,
                "summary": c.summary,
                "source_agent": c.source_agent or "user",
                "content": f"[{c.platform.upper()} Transcript] {c.title}: {c.summary}",
                "messages": messages,
                "messages_count": len(messages),
                "created_at": c.created_at,
                "score": round(score, 4),
                "lexical_score": lexical,
                "retrieval_method": "lexical+vector"
                if lexical and semantic is not None
                else "lexical"
                if lexical
                else "vector",
                "evidence": snippets,
            }
            if semantic is not None:
                result["vector_score"] = semantic
            best.append(result)
            best.sort(key=lambda item: (-item["score"], item["id"]))
            if len(best) > limit:
                best.pop()
        return best


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
                    msgs_preview = "\n".join(
                        f"{m.get('role', 'user')}: {m.get('content', '')[:100]}"
                        for m in msgs[:4]
                    )
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

def get_memories(
    page: int = 1,
    limit: int = 20,
    category: Optional[str] = None,
    source_agent: Optional[str] = None,
    q: Optional[str] = None,
    project_id: Optional[str] = None,
) -> Dict[str, Any]:
    page = max(1, page)
    limit = max(1, min(limit, 100))
    with Session(engine) as session:
        stmt = select(MemoryItem).where(MemoryItem.parent_id == None)
        if project_id and project_id.strip():
            raise ValueError("Project-scoped memory listing is not yet supported")
        if q and q.strip():
            stmt = stmt.where(MemoryItem.content.icontains(q.strip(), autoescape=True))
        if category:
            stmt = stmt.where(MemoryItem.category == category)
        if source_agent:
            stmt = stmt.where(MemoryItem.source_agent == source_agent)

        total = session.exec(select(func.count()).select_from(stmt.subquery())).one()

        offset = (page - 1) * limit
        items = session.exec(
            stmt.order_by(MemoryItem.created_at.desc()).offset(offset).limit(limit)
        ).all()

        res_memories = [
            _memory_response(mem, session.get(MemoryIndexState, mem.id))
            for mem in items
        ]

        pages = (total + limit - 1) // limit if limit > 0 else 1
        return {
            "memories": res_memories,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": pages,
        }


def delete_memory(memory_id: str) -> bool:
    with Session(engine) as session:
        items = session.exec(
            select(MemoryItem).where(
                (MemoryItem.id == memory_id) | (MemoryItem.parent_id == memory_id)
            )
        ).all()
        if not items:
            return False
        session.exec(
            delete(MemoryIndexState).where(MemoryIndexState.memory_id == memory_id)
        )
        for item in items:
            session.delete(item)
        session.commit()
        return True


def reset_all_memories() -> int:
    with Session(engine) as session:
        items = session.exec(select(MemoryItem)).all()
        count = sum(item.parent_id is None for item in items)
        session.exec(delete(MemoryIndexState))
        for item in items:
            session.delete(item)
        session.commit()
        return count


def export_all_memories() -> List[Dict[str, Any]]:
    with Session(engine) as session:
        mems = session.exec(
            select(MemoryItem).order_by(MemoryItem.created_at.desc())
        ).all()
        return [
            _memory_response(m, session.get(MemoryIndexState, m.parent_id or m.id))
            for m in mems
        ]


def update_memory(
    memory_id: str,
    content: Optional[str] = None,
    category: Optional[str] = None,
    source_agent: Optional[str] = None,
    tags: Optional[List[str]] = None,
    attachments: Optional[List[Dict[str, Any]]] = None,
    *,
    expected_revision: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    if content is not None and (
        not isinstance(content, str) or not content.strip() or len(content) > 50000
    ):
        raise HTTPException(422, "Memory content must contain 1 to 50000 characters")
    with Session(engine) as session:
        item = session.get(MemoryItem, memory_id)
        if not item or item.parent_id is not None:
            return None
        state = session.get(MemoryIndexState, memory_id)
        if state is None:
            timestamp = _now()
            session.exec(
                text("""INSERT INTO memory_index_state
                (memory_id, revision, index_status, created_at, updated_at)
                VALUES (:id, 0, 'pending', :created_at, :updated_at)
                ON CONFLICT (memory_id) DO NOTHING"""),
                params={
                    "id": memory_id,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                },
            )
            state = session.get(MemoryIndexState, memory_id)
        old_revision = state.revision
        if expected_revision is not None and expected_revision != old_revision:
            raise HTTPException(status_code=409, detail="Memory revision conflict")
        needs_index = content is not None or state.index_status == "pending"
        values = {"updated_at": _now(), "revision": old_revision + 1}
        if needs_index:
            values.update(
                index_status="pending",
                index_error=None,
                indexed_revision=None,
                embedding_model=None,
                embedding_dimension=None,
            )
        elif state.index_status == "completed":
            values["indexed_revision"] = old_revision + 1
        result = session.exec(
            update(MemoryIndexState)
            .where(
                MemoryIndexState.memory_id == memory_id,
                MemoryIndexState.revision == old_revision,
            )
            .values(**values)
        )
        if result.rowcount != 1:
            session.rollback()
            raise HTTPException(status_code=409, detail="Memory revision conflict")
        if content is not None:
            item.content = content
            item.embedding_json = "[]"
            item.total_chunks = None
            session.exec(delete(MemoryItem).where(MemoryItem.parent_id == memory_id))
            if is_postgres:
                session.exec(
                    text("UPDATE memories SET embedding_vector = NULL WHERE id = :id"),
                    params={"id": memory_id},
                )
        children = session.exec(
            select(MemoryItem).where(MemoryItem.parent_id == memory_id)
        ).all()
        for target in [item, *children]:
            if category is not None:
                target.category = category
            if source_agent is not None:
                target.source_agent = source_agent
            if tags is not None:
                target.tags_json = json.dumps(tags)
            if attachments is not None:
                target.attachments_json = json.dumps(attachments)
            session.add(target)
        item.last_accessed = _now()
        if attachments is not None:
            _register_attachment_metadata(
                session, attachments, item.source_agent, item.last_accessed
            )
        source_content = item.content
        session.commit()
    if needs_index:
        _index_memory(memory_id, old_revision + 1, source_content)
    with Session(engine) as session:
        item = session.get(MemoryItem, memory_id)
        return (
            _memory_response(item, session.get(MemoryIndexState, memory_id))
            if item
            else None
        )


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

def get_conversation(conv_id: str) -> Optional[Dict[str, Any]]:
    from gigamind.services.conversation_ledger import get_receipt

    with Session(engine) as session:
        conv = session.get(ConversationItem, conv_id)
        if conv is None:
            return None
        return {
            "id": conv.id, "platform": conv.platform, "title": conv.title,
            "summary": conv.summary, "source_agent": conv.source_agent or "user",
            "messages": json.loads(conv.messages_json or "[]"),
            "provenance": get_receipt(conv_id, engine=engine),
            "is_vectorized": bool(conv.embedding_json and conv.embedding_json != "[]"),
            "created_at": conv.created_at,
        }


def delete_conversation(conv_id: str, *, actor=None) -> bool:
    from gigamind.services.conversation_ledger import forget

    return forget(conv_id, actor=actor, engine=engine)

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
        def count(model, *conditions):
            return session.exec(select(func.count()).select_from(model).where(*conditions)).one()

        agent = func.coalesce(func.nullif(MemoryItem.source_agent, ""), "user")
        distribution = session.exec(
            select(agent, func.count())
            .where(MemoryItem.parent_id == None)
            .group_by(agent)
        ).all()
        return {
            "total_memories": count(MemoryItem, MemoryItem.parent_id == None),
            "total_profile_rules": count(ProfileItem),
            "total_chat_logs": count(ConversationItem),
            "total_task_sessions": count(TaskSessionItem),
            "total_storage_files": count(StorageFileItem),
            "total_storage_chunks": count(StorageChunkItem),
            "source_distribution": dict(distribution),
        }
