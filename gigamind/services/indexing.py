import os
import json
import math
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from sqlmodel import Session, select, text
from gigamind.db.database import engine, is_postgres, StorageFileItem, StorageChunkItem
from gigamind.services.parser import extract_text_from_file
from gigamind.services.chunking import chunk_text
from gigamind.services import embedding
from gigamind.services.embedding import generate_embedding
from gigamind.services.storage import storage_service


def _validate_vector(vector):
    try:
        valid = (
            isinstance(vector, (list, tuple))
            and len(vector) == embedding.DEFAULT_DIM
            and embedding.DEFAULT_DIM > 0
            and all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                for value in vector
            )
            and any(float(value) != 0 for value in vector)
        )
    except (TypeError, ValueError, OverflowError):
        valid = False
    if not valid:
        raise ValueError("Invalid embedding vector")
    return [float(value) for value in vector]


def index_file_content(
    file_key: str,
    filename: str,
    data: bytes,
    mime_type: Optional[str] = None,
    source_agent: str = "user",
    size_bytes: int = 0,
    publication_guard=None,
) -> Dict[str, Any]:
    """
    Parses binary data, extracts semantic text, chunks it, computes 768-dim embeddings,
    and saves file + chunk entities in Neon PostgreSQL with pgvector HNSW indexing.
    """
    now_str = datetime.now(timezone.utc).isoformat()
    file_id = f"file_{uuid.uuid4().hex[:12]}"
    if not size_bytes and data:
        size_bytes = len(data)
    parsed = extract_text_from_file(data=data, filename=filename, mime_type=mime_type)
    multimodal_type = parsed.get("format", "text")
    mime_type = parsed.get("mime_type") or mime_type

    if not parsed["supported"] or not parsed["text"].strip():
        # Unsupported or empty file: save record with status
        status = "unsupported" if parsed.get("format") == "binary" else "empty"
        with Session(engine) as session:
            if publication_guard:
                publication_guard(session)
            existing = session.exec(
                select(StorageFileItem).where(StorageFileItem.key == file_key)
            ).first()
            old_chunks = session.exec(
                select(StorageChunkItem).where(StorageChunkItem.file_key == file_key)
            ).all()
            for chunk in old_chunks:
                session.delete(chunk)
            if existing:
                file_id = existing.id
                existing.filename = filename
                existing.size_bytes = size_bytes
                existing.extracted_text_length = 0
                existing.total_chunks = 0
                existing.document_summary = None
                existing.embedding_json = "[]"
                existing.indexing_status = status
                existing.multimodal_type = multimodal_type
                existing.updated_at = now_str
            else:
                f_item = StorageFileItem(
                    id=file_id,
                    key=file_key,
                    filename=filename,
                    mime_type=mime_type or "application/octet-stream",
                    multimodal_type=multimodal_type,
                    size_bytes=size_bytes,
                    source_agent=source_agent or "user",
                    extracted_text_length=0,
                    total_chunks=0,
                    indexing_status=status,
                    created_at=now_str,
                    updated_at=now_str,
                )
                session.add(f_item)
            session.flush()
            if is_postgres:
                session.exec(
                    text(
                        "UPDATE storage_files SET embedding_vector = NULL WHERE id = :id"
                    ),
                    params={"id": file_id},
                )
            session.commit()

        return {
            "file_id": file_id,
            "key": file_key,
            "filename": filename,
            "multimodal_type": multimodal_type,
            "status": status,
            "chunks_created": 0,
            "extracted_length": 0,
            "reason": parsed.get("error"),
        }

    # Each PDF page gets a visual anchor, including pages without extractable text.
    raw_chunks: List[Dict[str, Any]] = []
    pages = parsed.get("pages", [])
    if multimodal_type == "pdf":
        for page in pages:
            number = page["page_number"]
            raw_chunks.append(
                {
                    "content": f"PDF page {number}",
                    "page_number": number,
                    "inline_bytes": page["raw_bytes"],
                    "mime_type": "application/pdf",
                    "is_visual_anchor": True,
                }
            )
            if page["text"]:
                for chunk in chunk_text(
                    page["text"], chunk_size=1200, chunk_overlap=200, min_threshold=1500
                ):
                    raw_chunks.append(
                        {"content": chunk["content"], "page_number": number}
                    )
    elif multimodal_type == "image":
        raw_chunks.append(
            {
                "content": parsed["text"],
                "page_number": 1,
                "inline_bytes": data,
                "mime_type": parsed["mime_type"],
                "is_visual_anchor": True,
            }
        )
    else:
        for chunk in chunk_text(
            parsed["text"], chunk_size=1200, chunk_overlap=200, min_threshold=1500
        ):
            raw_chunks.append({"content": chunk["content"], "page_number": 1})

    total_chunks = len(raw_chunks)
    if not total_chunks:
        raise ValueError("No indexable content")
    chunk_records: List[StorageChunkItem] = []
    chunk_embeddings: List[List[float]] = []
    for idx, rc in enumerate(raw_chunks):
        if rc.get("inline_bytes"):
            emb = generate_embedding(
                inline_bytes=rc["inline_bytes"], mime_type=rc["mime_type"]
            )
        else:
            emb = generate_embedding(text=rc["content"])
        emb = _validate_vector(emb)
        chunk_embeddings.append(emb)
        chunk_records.append(
            StorageChunkItem(
                id=f"{file_id}_chk_{idx}",
                file_id=file_id,
                file_key=file_key,
                filename=filename,
                chunk_index=idx,
                total_chunks=total_chunks,
                page_number=rc.get("page_number"),
                is_visual_anchor=rc.get("is_visual_anchor", False),
                content=rc["content"],
                embedding_json=json.dumps(emb),
                created_at=now_str,
            )
        )
    # The mean is a navigation vector, not a claim of document-level semantic quality.
    doc_embedding = _validate_vector(
        [
            sum(vector[i] for vector in chunk_embeddings) / len(chunk_embeddings)
            for i in range(embedding.DEFAULT_DIM)
        ]
    )

    # Persist in Neon DB
    with Session(engine) as session:
        if publication_guard:
            publication_guard(session)
        # Remove any old file record or chunks for this key
        old_chunks = session.exec(
            select(StorageChunkItem).where(StorageChunkItem.file_key == file_key)
        ).all()
        for oc in old_chunks:
            session.delete(oc)

        existing_file = session.exec(
            select(StorageFileItem).where(StorageFileItem.key == file_key)
        ).first()
        if existing_file:
            existing_file.filename = filename
            existing_file.mime_type = mime_type or existing_file.mime_type
            existing_file.multimodal_type = multimodal_type
            existing_file.size_bytes = size_bytes
            existing_file.extracted_text_length = len(parsed["text"])
            existing_file.total_chunks = total_chunks
            existing_file.indexing_status = "completed"
            existing_file.document_summary = parsed["text"][:350]
            existing_file.embedding_json = json.dumps(doc_embedding)
            existing_file.updated_at = now_str
            file_id = existing_file.id
            for chk in chunk_records:
                chk.file_id = file_id
        else:
            file_entity = StorageFileItem(
                id=file_id,
                key=file_key,
                filename=filename,
                mime_type=mime_type or "application/octet-stream",
                multimodal_type=multimodal_type,
                size_bytes=size_bytes,
                source_agent=source_agent or "user",
                extracted_text_length=len(parsed["text"]),
                total_chunks=total_chunks,
                indexing_status="completed",
                document_summary=parsed["text"][:350],
                embedding_json=json.dumps(doc_embedding),
                created_at=now_str,
                updated_at=now_str,
            )
            session.add(file_entity)

        for chk in chunk_records:
            session.add(chk)

        session.flush()
        if is_postgres:
            doc_vec_str = f"[{','.join(str(x) for x in doc_embedding)}]"
            session.exec(
                text(
                    "UPDATE storage_files SET embedding_vector = CAST(:vec AS vector) WHERE id = :id"
                ),
                params={"vec": doc_vec_str, "id": file_id},
            )
            for chk, emb in zip(chunk_records, chunk_embeddings):
                vec_str = f"[{','.join(str(x) for x in emb)}]"
                session.exec(
                    text(
                        "UPDATE storage_chunks SET embedding_vector = CAST(:vec AS vector) WHERE id = :id"
                    ),
                    params={"vec": vec_str, "id": chk.id},
                )
        session.commit()

    return {
        "file_id": file_id,
        "key": file_key,
        "filename": filename,
        "multimodal_type": multimodal_type,
        "status": "completed",
        "chunks_created": total_chunks,
        "extracted_length": len(parsed["text"]),
    }


def reindex_storage_file_by_key(
    key: str, publication_guard=None
) -> Optional[Dict[str, Any]]:
    """Downloads an existing file from R2 and executes full re-indexing."""
    if not storage_service.is_enabled():
        return None

    data = storage_service.download_file(key)
    if data is None:
        return None

    with Session(engine) as session:
        stored = session.exec(
            select(StorageFileItem).where(StorageFileItem.key == key)
        ).first()
        filename = stored.filename if stored else key.split("/")[-1]
        mime_type = stored.mime_type if stored else None
        source_agent = stored.source_agent if stored else "user"
    return index_file_content(
        file_key=key,
        filename=filename,
        data=data,
        mime_type=mime_type,
        source_agent=source_agent,
        publication_guard=publication_guard,
    )


def delete_storage_file_index(key: str) -> bool:
    """Deletes index metadata and all associated vector chunks for an R2 key."""
    with Session(engine) as session:
        chunks = session.exec(
            select(StorageChunkItem).where(StorageChunkItem.file_key == key)
        ).all()
        for chk in chunks:
            session.delete(chk)

        f_item = session.exec(
            select(StorageFileItem).where(StorageFileItem.key == key)
        ).first()
        if f_item:
            session.delete(f_item)

        session.commit()
    return True


def delete_all_storage_file_indexes() -> int:
    """Purges all storage file metadata and chunks from the database."""
    with Session(engine) as session:
        all_chunks = session.exec(select(StorageChunkItem)).all()
        count = len(all_chunks)
        for c in all_chunks:
            session.delete(c)

        all_files = session.exec(select(StorageFileItem)).all()
        for f in all_files:
            session.delete(f)

        session.commit()
        return count


def list_indexed_storage_files(limit: int = 100) -> List[Dict[str, Any]]:
    """Returns list of indexed files with chunk counts, statuses, and presigned download links."""
    with Session(engine) as session:
        files = session.exec(
            select(StorageFileItem)
            .order_by(StorageFileItem.created_at.desc())
            .limit(limit)
        ).all()
        res = []
        for f in files:
            url = None
            if storage_service.is_enabled():
                url = storage_service.get_presigned_download_url(
                    f.key, filename=f.filename
                )

            res.append(
                {
                    "id": f.id,
                    "key": f.key,
                    "filename": f.filename,
                    "mime_type": f.mime_type,
                    "size_bytes": f.size_bytes,
                    "source_agent": f.source_agent,
                    "extracted_text_length": f.extracted_text_length,
                    "total_chunks": f.total_chunks,
                    "indexing_status": f.indexing_status,
                    "url": url,
                    "created_at": f.created_at,
                    "updated_at": f.updated_at,
                }
            )
        return res


def get_file_chunks(key: str) -> List[Dict[str, Any]]:
    """Returns all semantic chunks and page citations extracted from a specific file key."""
    with Session(engine) as session:
        chunks = session.exec(
            select(StorageChunkItem)
            .where(StorageChunkItem.file_key == key)
            .order_by(StorageChunkItem.chunk_index.asc())
        ).all()
        return [
            {
                "id": c.id,
                "file_key": c.file_key,
                "chunk_index": c.chunk_index,
                "total_chunks": c.total_chunks,
                "page_number": c.page_number,
                "is_visual_anchor": c.is_visual_anchor,
                "content": c.content,
                "created_at": c.created_at,
            }
            for c in chunks
        ]


def register_storage_file(
    file_key: str,
    filename: str,
    mime_type: Optional[str] = None,
    size_bytes: int = 0,
    source_agent: str = "user",
) -> StorageFileItem:
    """Inserts or updates a StorageFileItem immediately so the file is recorded in the Files repository."""
    now_str = datetime.now(timezone.utc).isoformat()
    ext = os.path.splitext(filename or "")[1].lower()
    m_type = (
        "pdf"
        if ext == ".pdf" or (mime_type and "pdf" in mime_type)
        else (
            "image"
            if ext in [".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"]
            or (mime_type and mime_type.startswith("image/"))
            else (
                "code" if ext in [".py", ".ts", ".js", ".sql", ".rs", ".go"] else "text"
            )
        )
    )

    with Session(engine) as session:
        existing = session.exec(
            select(StorageFileItem).where(StorageFileItem.key == file_key)
        ).first()
        if not existing:
            f_item = StorageFileItem(
                id=f"file_{uuid.uuid4().hex[:12]}",
                key=file_key,
                filename=filename,
                mime_type=mime_type or "application/octet-stream",
                multimodal_type=m_type,
                size_bytes=size_bytes,
                source_agent=source_agent or "user",
                extracted_text_length=0,
                total_chunks=0,
                indexing_status="completed"
                if not storage_service.is_enabled()
                else "pending",
                created_at=now_str,
                updated_at=now_str,
            )
            session.add(f_item)
            session.commit()
            session.refresh(f_item)
            return f_item
        else:
            existing.filename = filename
            existing.multimodal_type = m_type
            if mime_type:
                existing.mime_type = mime_type
            if size_bytes:
                existing.size_bytes = size_bytes
            existing.updated_at = now_str
            session.add(existing)
            session.commit()
            session.refresh(existing)
            return existing
