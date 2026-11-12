"""Bounded candidates from published file text and vectors, without remote IO."""

import json
import math

from sqlmodel import select, text
from sqlalchemy import and_

from gigamind.db.database import StorageFileItem, StorageChunkItem
from gigamind.db.jobs import ResourceJobState
from gigamind.services.embedding import (
    EmbeddingUnavailable,
    cosine_similarity,
    validate_embedding_vector,
)


def _order(item):
    return (
        -item["score"],
        item["file_key"],
        0 if "page_number" in item else 1,
        item.get("chunk_index", 0),
        item["id"],
    )


class _FilePool:
    def __init__(self, capacity):
        self.capacity = capacity
        self.items = {}

    def offer(self, candidate):
        key = candidate["file_key"]
        previous = self.items.get(key)
        if previous is not None:
            pages = sorted(
                set(previous["matching_pages"] + candidate["matching_pages"])
            )[:8]
            best = candidate if _order(candidate) < _order(previous) else previous
            best["matching_pages"] = pages
            self.items[key] = best
        elif len(self.items) < self.capacity:
            self.items[key] = candidate
        else:
            worst = max(self.items, key=lambda stored: _order(self.items[stored]))
            if _order(candidate) < _order(self.items[worst]):
                del self.items[worst]
                self.items[key] = candidate

    def results(self):
        return sorted(self.items.values(), key=_order)


def _document(item):
    return {
        "id": item.id,
        "_record_type": "document",
        "file_id": item.id,
        "file_key": item.key,
        "filename": item.filename,
        "content": item.document_summary or f"[{item.filename}]",
        "source": "file",
        "category": "file",
        "source_agent": item.source_agent,
        "multimodal_type": item.multimodal_type or "text",
        "chunk_index": 0,
        "total_chunks": item.total_chunks or 1,
        "matching_pages": [],
        "url": "",
    }


def _chunk(item, source_agent, multimodal_type):
    candidate = {
        "id": item.id,
        "_record_type": "chunk",
        "file_id": item.file_id,
        "file_key": item.file_key,
        "filename": item.filename,
        "content": item.content,
        "source": "file",
        "category": "file",
        "chunk_index": item.chunk_index,
        "total_chunks": item.total_chunks,
        "page_number": item.page_number,
        "is_visual_anchor": item.is_visual_anchor,
        "matching_pages": [item.page_number] if item.page_number is not None else [],
        "multimodal_type": multimodal_type or "text",
        "url": "",
    }
    if source_agent is not None:
        candidate["source_agent"] = source_agent
    return candidate


def _visible(key_column):
    return (
        ~select(ResourceJobState.key)
        .where(ResourceJobState.key == key_column, ResourceJobState.deleted.is_(True))
        .exists()
    )


def _local_similarity(query_vector, raw):
    try:
        stored = validate_embedding_vector(json.loads(raw))
    except (EmbeddingUnavailable, ValueError, TypeError):
        return None
    score = cosine_similarity(query_vector, stored)
    return score if math.isfinite(score) else None


def file_candidates(
    session,
    *,
    query_vector,
    lexical_hits,
    term_count,
    source_agent,
    category,
    capacity,
    is_postgres,
):
    # Files have one category; chunks inherit source identity only from a matching parent.
    if category and category != "file":
        return [], []
    lexical, vectors = _FilePool(capacity), _FilePool(capacity)
    source_agent = source_agent or None
    if term_count or (query_vector is not None and not is_postgres):
        documents = select(StorageFileItem).where(_visible(StorageFileItem.key))
        chunks = (
            select(
                StorageChunkItem,
                StorageFileItem.source_agent,
                StorageFileItem.multimodal_type,
            )
            .outerjoin(
                StorageFileItem,
                and_(
                    StorageFileItem.id == StorageChunkItem.file_id,
                    StorageFileItem.key == StorageChunkItem.file_key,
                ),
            )
            .where(_visible(StorageChunkItem.file_key))
        )
        if source_agent is not None:
            documents = documents.where(StorageFileItem.source_agent == source_agent)
            chunks = chunks.where(StorageFileItem.source_agent == source_agent)
        for item in session.exec(documents.execution_options(yield_per=100)):
            hits = (
                lexical_hits(item.filename + " " + (item.document_summary or ""))
                if term_count
                else 0
            )
            candidate = _document(item)
            if hits:
                lexical.offer(
                    {
                        **candidate,
                        "score": hits / term_count * 0.4,
                        "retrieval_method": "lexical",
                    }
                )
            if query_vector is not None and not is_postgres:
                score = _local_similarity(query_vector, item.embedding_json)
                if score is not None:
                    vectors.offer(
                        {
                            **candidate,
                            "score": score,
                            "vector_score": score,
                            "retrieval_method": "vector",
                        }
                    )
        for item, owner_source, kind in session.exec(
            chunks.execution_options(yield_per=100)
        ):
            hits = lexical_hits(item.content) if term_count else 0
            candidate = _chunk(item, owner_source, kind)
            if hits:
                lexical.offer(
                    {
                        **candidate,
                        "score": hits / term_count * 0.4,
                        "retrieval_method": "lexical",
                    }
                )
            if query_vector is not None and not is_postgres:
                score = _local_similarity(query_vector, item.embedding_json)
                if score is not None:
                    vectors.offer(
                        {
                            **candidate,
                            "score": score,
                            "vector_score": score,
                            "retrieval_method": "vector",
                        }
                    )
    if is_postgres and query_vector is not None:
        params = {
            "vec": "[" + ",".join(str(value) for value in query_vector) + "]",
            "source_agent": source_agent,
            "capacity": max(30, capacity),
        }
        documents = text("""
            SELECT f.id, f.key, f.filename, f.document_summary, f.source_agent,
                   f.multimodal_type, f.total_chunks,
                   1.0 - (f.embedding_vector <=> CAST(:vec AS vector)) AS vector_score
            FROM storage_files f
            WHERE f.embedding_vector IS NOT NULL
              AND (:source_agent IS NULL OR f.source_agent = :source_agent)
              AND NOT EXISTS (SELECT 1 FROM resource_job_state r WHERE r.key = f.key AND r.deleted IS TRUE)
            ORDER BY f.embedding_vector <=> CAST(:vec AS vector), f.key, f.id
            LIMIT :capacity
        """)
        for item in session.exec(documents, params=params):
            score = float(item.vector_score)
            if math.isfinite(score):
                vectors.offer(
                    {
                        **_document(item),
                        "score": score,
                        "vector_score": score,
                        "retrieval_method": "vector",
                    }
                )
        params["capacity"] = max(60, capacity)
        chunks = text("""
            SELECT c.id, c.file_id, c.file_key, c.filename, c.chunk_index, c.total_chunks,
                   c.page_number, c.content, c.is_visual_anchor, f.source_agent, f.multimodal_type,
                   1.0 - (c.embedding_vector <=> CAST(:vec AS vector)) AS vector_score
            FROM storage_chunks c
            LEFT JOIN storage_files f ON f.id = c.file_id AND f.key = c.file_key
            WHERE c.embedding_vector IS NOT NULL
              AND (:source_agent IS NULL OR f.source_agent = :source_agent)
              AND NOT EXISTS (SELECT 1 FROM resource_job_state r WHERE r.key = c.file_key AND r.deleted IS TRUE)
            ORDER BY c.embedding_vector <=> CAST(:vec AS vector), c.file_key, c.chunk_index, c.id
            LIMIT :capacity
        """)
        for item in session.exec(chunks, params=params):
            score = float(item.vector_score)
            if math.isfinite(score):
                vectors.offer(
                    {
                        **_chunk(item, item.source_agent, item.multimodal_type),
                        "score": score,
                        "vector_score": score,
                        "retrieval_method": "vector",
                    }
                )
    return lexical.results(), vectors.results()
