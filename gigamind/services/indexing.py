import json
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from sqlmodel import Session, select, text

from gigamind.db.database import engine, is_postgres, StorageFileItem, StorageChunkItem
from gigamind.services.parser import extract_text_from_file
from gigamind.services.chunking import chunk_text
from gigamind.services.embedding import generate_embedding
from gigamind.services.storage import storage_service


def index_file_content(
    file_key: str,
    filename: str,
    data: bytes,
    mime_type: Optional[str] = None,
    source_agent: str = "user",
    size_bytes: int = 0
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

    if not parsed["supported"] or not parsed["text"].strip():
        # Unsupported or empty file: save record with status
        status = "unsupported" if parsed.get("format") == "binary" else "empty"
        with Session(engine) as session:
            # Check if file record already exists
            existing = session.exec(select(StorageFileItem).where(StorageFileItem.key == file_key)).first()
            if existing:
                existing.indexing_status = status
                existing.updated_at = now_str
            else:
                f_item = StorageFileItem(
                    id=file_id,
                    key=file_key,
                    filename=filename,
                    mime_type=mime_type or "application/octet-stream",
                    size_bytes=size_bytes,
                    source_agent=source_agent or "user",
                    extracted_text_length=0,
                    total_chunks=0,
                    indexing_status=status,
                    created_at=now_str,
                    updated_at=now_str
                )
                session.add(f_item)
            session.commit()

        return {
            "file_id": file_id,
            "key": file_key,
            "filename": filename,
            "status": status,
            "chunks_created": 0,
            "extracted_length": 0
        }

    # Generate semantic chunks with page / line tracking
    raw_chunks: List[Dict[str, Any]] = []

    pages = parsed.get("pages", [])
    if pages and len(pages) > 1:
        # Multi-page document (e.g. PDF): chunk per page
        for p in pages:
            p_num = p["page_number"]
            p_text = p["text"].strip()
            if not p_text:
                continue
            sub_chunks = chunk_text(p_text, chunk_size=500, chunk_overlap=100, min_threshold=600)
            for sc in sub_chunks:
                raw_chunks.append({
                    "content": sc["content"],
                    "page_number": p_num
                })
    else:
        # Single page / code / markdown
        sub_chunks = chunk_text(parsed["text"], chunk_size=500, chunk_overlap=100, min_threshold=600)
        for sc in sub_chunks:
            raw_chunks.append({
                "content": sc["content"],
                "page_number": 1
            })

    total_chunks = len(raw_chunks)
    chunk_records: List[StorageChunkItem] = []
    chunk_embeddings: List[List[float]] = []

    for idx, rc in enumerate(raw_chunks):
        chk_id = f"{file_id}_chk_{idx}"
        emb = generate_embedding(rc["content"])
        chunk_embeddings.append(emb)

        chunk_item = StorageChunkItem(
            id=chk_id,
            file_id=file_id,
            file_key=file_key,
            filename=filename,
            chunk_index=idx,
            total_chunks=total_chunks,
            page_number=rc.get("page_number"),
            content=rc["content"],
            embedding_json=json.dumps(emb),
            created_at=now_str
        )
        chunk_records.append(chunk_item)

    # Persist in Neon DB
    with Session(engine) as session:
        # Remove any old file record or chunks for this key
        old_chunks = session.exec(select(StorageChunkItem).where(StorageChunkItem.file_key == file_key)).all()
        for oc in old_chunks:
            session.delete(oc)

        existing_file = session.exec(select(StorageFileItem).where(StorageFileItem.key == file_key)).first()
        if existing_file:
            existing_file.filename = filename
            existing_file.mime_type = mime_type or existing_file.mime_type
            existing_file.size_bytes = size_bytes
            existing_file.extracted_text_length = len(parsed["text"])
            existing_file.total_chunks = total_chunks
            existing_file.indexing_status = "completed"
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
                size_bytes=size_bytes,
                source_agent=source_agent or "user",
                extracted_text_length=len(parsed["text"]),
                total_chunks=total_chunks,
                indexing_status="completed",
                created_at=now_str,
                updated_at=now_str
            )
            session.add(file_entity)

        for chk in chunk_records:
            session.add(chk)

        session.commit()

        # Update pgvector embedding_vector column for PostgreSQL
        if is_postgres:
            try:
                with Session(engine) as p_sess:
                    for idx, chk in enumerate(chunk_records):
                        emb = chunk_embeddings[idx]
                        vec_str = f"[{','.join(str(x) for x in emb)}]"
                        p_sess.exec(
                            text("UPDATE storage_chunks SET embedding_vector = CAST(:vec AS vector) WHERE id = :id"),
                            params={"vec": vec_str, "id": chk.id}
                        )
                    p_sess.commit()
            except Exception as p_err:
                print(f"storage_chunks pgvector update note: {p_err}")

    return {
        "file_id": file_id,
        "key": file_key,
        "filename": filename,
        "status": "completed",
        "chunks_created": total_chunks,
        "extracted_length": len(parsed["text"])
    }


def reindex_storage_file_by_key(key: str) -> Optional[Dict[str, Any]]:
    """Downloads an existing file from R2 and executes full re-indexing."""
    if not storage_service.is_enabled():
        return None

    data = storage_service.download_file(key)
    if not data:
        return None

    filename = key.split("/")[-1]
    return index_file_content(file_key=key, filename=filename, data=data)


def delete_storage_file_index(key: str) -> bool:
    """Deletes index metadata and all associated vector chunks for an R2 key."""
    with Session(engine) as session:
        chunks = session.exec(select(StorageChunkItem).where(StorageChunkItem.file_key == key)).all()
        for chk in chunks:
            session.delete(chk)

        f_item = session.exec(select(StorageFileItem).where(StorageFileItem.key == key)).first()
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
        files = session.exec(select(StorageFileItem).order_by(StorageFileItem.created_at.desc()).limit(limit)).all()
        res = []
        for f in files:
            url = None
            if storage_service.is_enabled():
                url = storage_service.get_presigned_download_url(f.key, filename=f.filename)

            res.append({
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
                "updated_at": f.updated_at
            })
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
                "content": c.content,
                "created_at": c.created_at
            }
            for c in chunks
        ]
