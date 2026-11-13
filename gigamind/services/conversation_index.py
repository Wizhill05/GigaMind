"""Durable, source-first indexing of complete conversation transcripts."""

import hashlib
import json
import uuid

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from gigamind.db.conversation_index import (
    ConversationIndexSegment,
    ConversationIndexState,
)
from gigamind.db.conversation_ledger import ConversationReceipt, ConversationSource
from gigamind.db.database import ConversationItem
from gigamind.db.jobs import Job
from gigamind.services import embedding, jobs
from gigamind.services.conversation_ledger import transaction


def _source(connection, conversation_id, *, lock=False):
    query = select(ConversationItem.__table__).where(
        ConversationItem.id == conversation_id
    )
    if lock:
        query = query.with_for_update()
    row = connection.execute(query).mappings().first()
    if row is None:
        return None
    receipt = connection.execute(
        select(ConversationReceipt.deleted_at, ConversationSource.forgotten_at)
        .join(
            ConversationSource, ConversationReceipt.source_key == ConversationSource.key
        )
        .where(ConversationReceipt.conversation_id == conversation_id)
    ).first()
    if receipt and (receipt.deleted_at or receipt.forgotten_at):
        return None
    return dict(row)


def _fingerprint(row):
    fields = ("id", "platform", "title", "summary", "source_agent", "messages_json")
    encoded = json.dumps(
        [row[key] for key in fields], ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _segments(row):
    # JSON retains every role and message field, even for older transcript shapes.
    messages = json.loads(row["messages_json"] or "[]")
    if not isinstance(messages, list):
        raise ValueError("Invalid conversation messages")
    content = (
        "Title: "
        + (row["title"] or "")
        + "\nSummary: "
        + (row["summary"] or "")
        + "\nMessages: "
        + json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
    )
    limit = embedding.MAX_TEXT_BYTES - len("Conversation text: ".encode("utf-8"))
    chunks, chunk, size = [], [], 0
    for char in content:
        count = len(char.encode("utf-8"))
        if size + count > limit:
            chunks.append("".join(chunk))
            chunk, size = [], 0
        chunk.append(char)
        size += count
    if chunk:
        chunks.append("".join(chunk))
    return chunks


def enqueue_conversation(
    conversation_id,
    idempotency_key=None,
    max_attempts=3,
    *,
    engine=None,
    _skip_existing=False,
):
    jobs.validate_resource_key(conversation_id)
    if idempotency_key is not None and (
        not isinstance(idempotency_key, str)
        or not idempotency_key.strip()
        or len(idempotency_key) > 255
    ):
        raise ValueError("Invalid job options")
    if (
        isinstance(max_attempts, bool)
        or not isinstance(max_attempts, int)
        or not 1 <= max_attempts <= 20
    ):
        raise ValueError("Invalid job options")
    engine = jobs.resolve_engine(engine)
    payload = json.dumps(
        {"conversation_id": conversation_id}, sort_keys=True, separators=(",", ":")
    )
    try:
        with transaction(engine) as connection:
            row = _source(connection, conversation_id, lock=True)
            if row is None:
                raise LookupError("Conversation not found")
            if _skip_existing:
                info, _ = _snapshot(conversation_id, engine, connection=connection)
                if info and (
                    info["indexed"]
                    or info["state"] in ("queued", "running", "retrying")
                ):
                    return None
            old = None
            if idempotency_key is not None:
                old = connection.execute(
                    select(Job.__table__).where(Job.idempotency_key == idempotency_key)
                ).mappings().first()
            if old:
                if (
                    old["kind"] != "index_conversation"
                    or old["payload_json"] != payload
                    or old["max_attempts"] != max_attempts
                ):
                    raise jobs.Conflict(
                        "Idempotency key already used with different job parameters"
                    )
                result_id = old["id"]
            else:
                now = jobs.stamp(jobs.utcnow())
                result_id = uuid.uuid4().hex
                state = ConversationIndexState.__table__
                existing = connection.execute(
                    select(state.c.conversation_id).where(
                        state.c.conversation_id == conversation_id
                    )
                ).first()
                values = dict(
                    current_job_id=result_id,
                    requested_fingerprint=_fingerprint(row),
                    updated_at=now,
                )
                if existing:
                    connection.execute(
                        update(state)
                        .where(state.c.conversation_id == conversation_id)
                        .values(**values)
                    )
                else:
                    connection.execute(
                        state.insert().values(
                            conversation_id=conversation_id, segment_count=0, **values
                        )
                    )
                connection.execute(
                    update(Job)
                    .where(
                        Job.kind == "index_conversation",
                        Job.resource_key == conversation_id,
                        Job.state.in_(["queued", "retrying", "running"]),
                    )
                    .values(
                        state="cancelled", lease_token=None, lease_deadline=None,
                        updated_at=now,
                    )
                )
                connection.execute(
                    Job.__table__.insert().values(
                        id=result_id, kind="index_conversation",
                        resource_key=conversation_id, payload_json=payload,
                        idempotency_key=idempotency_key, state="queued", attempts=0,
                        max_attempts=max_attempts, available_at=now,
                        created_at=now, updated_at=now,
                    )
                )
    except IntegrityError:
        if idempotency_key is None:
            raise
        with transaction(engine) as connection:
            if _source(connection, conversation_id, lock=True) is None:
                raise LookupError("Conversation not found")
            old = connection.execute(
                select(Job.__table__).where(Job.idempotency_key == idempotency_key)
            ).mappings().first()
            if (
                old is None
                or old["kind"] != "index_conversation"
                or old["payload_json"] != payload
                or old["max_attempts"] != max_attempts
            ):
                raise jobs.Conflict(
                    "Idempotency key already used with different job parameters"
                )
            result_id = old["id"]
    return jobs.status(result_id, engine=engine)


def index_conversation(payload, lease):
    conversation_id = payload["conversation_id"]
    engine = jobs.resolve_engine(lease.engine)
    with engine.connect() as connection:
        row = _source(connection, conversation_id)
    if row is None:
        raise jobs.PermanentFailure("Conversation no longer exists")
    fingerprint = _fingerprint(row)
    model, dimension = embedding.MODEL_NAME, embedding.DEFAULT_DIM
    if (
        not isinstance(model, str)
        or not model.strip()
        or not isinstance(dimension, int)
        or isinstance(dimension, bool)
        or dimension <= 0
    ):
        raise ValueError("Invalid embedding model metadata")
    segments = _segments(row)
    vectors = [
        embedding.validate_embedding_vector(
            embedding.generate_embedding(text="Conversation text: " + part)
        )
        for part in segments
    ]
    if model != embedding.MODEL_NAME or dimension != embedding.DEFAULT_DIM:
        raise ValueError("Embedding configuration changed")
    with transaction(engine) as connection:
        current = _source(connection, conversation_id, lock=True)
        state = connection.execute(
            select(ConversationIndexState.__table__).where(
                ConversationIndexState.conversation_id == conversation_id
            )
        ).mappings().first()
        if (
            current is None
            or _fingerprint(current) != fingerprint
            or state is None
            or state["current_job_id"] != lease.job_id
            or state["requested_fingerprint"] != fingerprint
        ):
            raise jobs.PermanentFailure("Conversation source or job is no longer current")
        now = jobs.stamp(lease.clock())
        # This write locks the job and fences cancellation until commit.
        guarded = connection.execute(
            update(Job)
            .where(
                Job.id == lease.job_id,
                Job.kind == "index_conversation",
                Job.state == "running",
                Job.lease_token == lease.token,
                Job.lease_deadline > now,
            )
            .values(lease_token=lease.token)
        )
        if not guarded.rowcount:
            raise jobs.PermanentFailure("Job lease is no longer active")
        connection.execute(
            delete(ConversationIndexSegment).where(
                ConversationIndexSegment.conversation_id == conversation_id
            )
        )
        records = [
            dict(
                conversation_id=conversation_id,
                segment_index=i,
                content=part,
                embedding_json=json.dumps(vector, allow_nan=False),
            )
            for i, (part, vector) in enumerate(zip(segments, vectors))
        ]
        connection.execute(ConversationIndexSegment.__table__.insert(), records)
        connection.execute(
            update(ConversationIndexState)
            .where(
                ConversationIndexState.conversation_id == conversation_id
            )
            .values(
                indexed_fingerprint=fingerprint,
                model=model,
                dimension=dimension,
                segment_count=len(segments),
                updated_at=now,
            )
        )
    return {
        "conversation_id": conversation_id,
        "segments": len(segments),
        "model": model,
        "dimension": dimension,
    }


def _snapshot(conversation_id, engine, *, connection=None):
    """Read the source, ownership, and all segments in one database statement."""
    state = ConversationIndexState.__table__
    segment = ConversationIndexSegment.__table__
    receipt = ConversationReceipt.__table__
    source = ConversationSource.__table__
    transcript = ConversationItem.__table__
    job = Job.__table__
    query = (
        select(
            transcript,
            state.c.current_job_id,
            state.c.indexed_fingerprint,
            state.c.model,
            state.c.dimension,
            state.c.segment_count,
            job.c.state.label("job_state"),
            job.c.error.label("job_error"),
            segment.c.segment_index,
            segment.c.content,
            segment.c.embedding_json.label("segment_embedding"),
        )
        .select_from(
            transcript.outerjoin(state, state.c.conversation_id == transcript.c.id)
            .outerjoin(job, job.c.id == state.c.current_job_id)
            .outerjoin(segment, segment.c.conversation_id == transcript.c.id)
            .outerjoin(receipt, receipt.c.conversation_id == transcript.c.id)
            .outerjoin(source, source.c.key == receipt.c.source_key)
        )
        .where(
            transcript.c.id == conversation_id,
            receipt.c.deleted_at.is_(None),
            source.c.forgotten_at.is_(None),
        )
        .order_by(segment.c.segment_index)
    )
    if connection is None:
        with engine.connect() as read_connection:
            rows = read_connection.execute(query).mappings().all()
    else:
        rows = connection.execute(query).mappings().all()
    if not rows:
        return None, []
    first = rows[0]
    indexed = bool(
        first["indexed_fingerprint"] == _fingerprint(first)
        and first["model"] == embedding.MODEL_NAME
        and first["dimension"] == embedding.DEFAULT_DIM
        and first["segment_count"]
        and len(rows) == first["segment_count"]
    )
    vectors = []
    if indexed:
        try:
            for position, row in enumerate(rows):
                if row["segment_index"] != position:
                    raise ValueError("Missing conversation segment")
                vector = embedding.validate_embedding_vector(
                    json.loads(row["segment_embedding"])
                )
                vectors.append(
                    {
                        "segment_index": position,
                        "content": row["content"],
                        "embedding": vector,
                        "model": first["model"],
                        "dimension": first["dimension"],
                    }
                )
        except (ValueError, TypeError, embedding.EmbeddingUnavailable):
            indexed, vectors = False, []
    fallback = (
        "legacy" if first["embedding_json"] not in (None, "", "[]") else "not_indexed"
    )
    job_state = first["job_state"]
    error = first["job_error"]
    if job_state == "completed" and not indexed:
        job_state = fallback
        error = "The conversation index is unavailable or outdated; reindex it."
    info = {
        "indexed": indexed,
        "job_id": first["current_job_id"],
        "state": job_state or fallback,
        "error": error,
        "model": first["model"],
        "dimension": first["dimension"],
        "segment_count": first["segment_count"] or 0,
    }
    return info, vectors


def metadata(conversation_id, *, engine=None):
    info, _ = _snapshot(conversation_id, jobs.resolve_engine(engine))
    return info


def segment_vectors(conversation_id, *, engine=None):
    _, vectors = _snapshot(conversation_id, jobs.resolve_engine(engine))
    return vectors


def enqueue_backfill(cursor=None, limit=20, *, engine=None):
    if cursor is not None and not isinstance(cursor, str):
        raise ValueError("Invalid cursor")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("Invalid limit")
    engine = jobs.resolve_engine(engine)
    with engine.connect() as connection:
        ids = connection.execute(
            select(ConversationItem.id)
            .where(ConversationItem.id > (cursor or ""))
            .order_by(ConversationItem.id)
            .limit(limit + 1)
        ).scalars().all()
    page = ids[:limit]
    queued, skipped = 0, 0
    for cid in page:
        try:
            job = enqueue_conversation(cid, engine=engine, _skip_existing=True)
            if job is None:
                skipped += 1
            else:
                queued += 1
        except LookupError:
            skipped += 1
    return {
        "queued": queued,
        "skipped": skipped,
        "next_cursor": page[-1] if len(ids) > limit else None,
    }
