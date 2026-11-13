"""Transactional, content-free attribution for legacy sources."""

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select
from gigamind.db.source_provenance import SourceHead, SourceReceipt


def lock_sources(session):
    """Acquire the source write lock before reading authoritative source state."""
    if session.in_transaction():
        raise RuntimeError("lock_sources must precede all transaction reads and writes")
    connection = session.connection()
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    elif connection.dialect.name == "postgresql":
        connection.exec_driver_sql("SELECT pg_advisory_xact_lock(723649823)")
    else:
        raise RuntimeError("unsupported database dialect")
    session.info["source_provenance_transaction"] = session.get_transaction()


def record_write(
    session,
    *,
    kind,
    source_id,
    operation,
    actor=None,
    payload=None,
    source_revision=None,
):
    """Append a receipt inside the caller's locked transaction."""
    tx = session.get_transaction()
    if (
        tx is None
        or session.info.get("source_provenance_transaction") is not tx
        or not tx.is_active
    ):
        raise RuntimeError("source transaction is not locked")
    if (
        kind not in ("memory", "profile", "file")
        or operation not in ("created", "updated", "deleted", "reset", "verified")
        or (operation == "verified" and kind != "file")
        or not isinstance(source_id, str)
        or not source_id.strip()
    ):
        raise ValueError("invalid source or operation")
    if actor is not None and (
        not actor.is_admin or not isinstance(actor.id, str) or not actor.id.strip()
    ):
        raise PermissionError("an authenticated writer must be an admin")
    if source_revision is not None and (
        type(source_revision) is not int or source_revision < 0
    ):
        raise ValueError("Invalid actual source revision")
    writer = actor.id if actor is not None else None
    provenance = "authenticated" if actor is not None else "unattributed"
    digest = (
        None
        if payload is None
        else hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
    )
    head = session.get(SourceHead, (kind, source_id))
    if head is None:
        head = SourceHead(
            kind=kind,
            source_id=source_id,
            revision=0,
            active=True,
            creator_id=writer if operation == "created" else None,
            creator_provenance=provenance
            if operation == "created"
            else "legacy_unknown",
        )
        session.add(head)
    head.revision += 1
    head.active = operation not in ("deleted", "reset")
    session.add(
        SourceReceipt(
            kind=kind,
            source_id=source_id,
            revision=head.revision,
            operation=operation,
            writer_id=writer,
            writer_provenance=provenance,
            payload_hash=digest,
            source_revision=None if source_revision is None else str(source_revision),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    )
    session.flush()
    return head.revision


def read_provenance(engine, kind, source_id, limit=20, offset=0):
    """Return a head and descending receipt page bounded by its revision."""
    if (
        kind not in ("memory", "profile", "file")
        or not isinstance(source_id, str)
        or not source_id.strip()
        or type(limit) is not int
        or type(offset) is not int
        or not 1 <= limit <= 100
        or not 0 <= offset <= 1_000_000
    ):
        raise ValueError("invalid source or pagination")
    with engine.connect() as conn:
        head = (
            conn.execute(
                select(SourceHead.__table__).where(
                    SourceHead.kind == kind, SourceHead.source_id == source_id
                )
            )
            .mappings()
            .first()
        )
        if head is None:
            return None
        receipts = (
            conn.execute(
                select(SourceReceipt.__table__)
                .where(
                    SourceReceipt.kind == kind,
                    SourceReceipt.source_id == source_id,
                    SourceReceipt.revision <= head["revision"],
                )
                .order_by(SourceReceipt.revision.desc())
                .limit(limit)
                .offset(offset)
            )
            .mappings()
            .all()
        )
        return {
            "head": dict(head),
            "receipts": [dict(row) for row in receipts],
            "total": head["revision"],
            "limit": limit,
            "offset": offset,
        }
