"""Atomic import receipts and durable upstream-identity forgetting."""

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import delete, select, text, update

from gigamind.db.conversation_ledger import (
    ConversationReceipt,
    ConversationSource,
    register_legacy,
)
from gigamind.db.database import ConversationItem
from gigamind.services.conversation_import import normalize_conversations


@contextmanager
def transaction(engine):
    # A batch may contain multiple source identities. A single lifecycle lock
    # avoids lock-order deadlocks and serializes import with forgetting.
    with engine.connect() as connection:
        if engine.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        elif engine.dialect.name == "postgresql":
            connection.begin()
            connection.execute(text("SELECT pg_advisory_xact_lock(723649822)"))
        else:
            raise RuntimeError("Unsupported conversation ledger database")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise


def source_identity(conversation):
    upstream = conversation["source_id"]
    kind = "upstream" if upstream is not None and upstream.strip() else "fingerprint"
    identity = (
        [kind, conversation["platform"], upstream]
        if kind == "upstream"
        else [kind, conversation["id"]]
    )
    key = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    return key, kind


def importer_provenance(actor, provenance):
    if actor is not None:
        if not actor.is_admin:
            from fastapi import HTTPException

            raise HTTPException(403, "Conversation imports require an administrator")
        return actor.id, "authenticated"
    if provenance not in {"unattributed", "local_cli"}:
        raise ValueError("Invalid unauthenticated import provenance")
    return None, provenance


def import_sources(
    raw, default_platform=None, *, actor=None, provenance="unattributed", engine
):
    imported_by, attribution = importer_provenance(actor, provenance)
    conversations = normalize_conversations(raw, default_platform)
    sources, receipts, transcripts = (
        ConversationSource.__table__,
        ConversationReceipt.__table__,
        ConversationItem.__table__,
    )
    now = datetime.now(timezone.utc).isoformat()
    records = []
    with transaction(engine) as connection:
        for conversation in conversations:
            cid = conversation["id"]
            source_key, kind = source_identity(conversation)
            receipt = (
                connection.execute(
                    select(receipts).where(receipts.c.conversation_id == cid)
                )
                .mappings()
                .first()
            )
            source = (
                connection.execute(select(sources).where(sources.c.key == source_key))
                .mappings()
                .first()
            )
            if (receipt and receipt["deleted_at"]) or (
                source and source["forgotten_at"]
            ):
                status = "forgotten"
            else:
                if source is None:
                    connection.execute(
                        sources.insert().values(
                            key=source_key,
                            platform=conversation["platform"],
                            upstream_id=conversation["source_id"]
                            if kind == "upstream"
                            else None,
                            identity_kind=kind,
                            created_at=now,
                        )
                    )
                if receipt is None:
                    exists = connection.execute(
                        select(transcripts.c.id).where(transcripts.c.id == cid)
                    ).first()
                    if not exists:
                        connection.execute(
                            transcripts.insert().values(
                                id=cid,
                                platform=conversation["platform"],
                                title=conversation["title"],
                                summary=conversation["summary"],
                                source_agent=conversation["source_agent"],
                                created_at=conversation["created_at"] or now,
                                messages_json=json.dumps(
                                    conversation["messages"], ensure_ascii=False
                                ),
                                embedding_json="[]",
                            )
                        )
                    connection.execute(
                        receipts.insert().values(
                            conversation_id=cid,
                            source_key=source_key,
                            content_digest=cid.removeprefix("import_"),
                            imported_at=now if not exists else None,
                            imported_by=imported_by if not exists else None,
                            provenance=attribution if not exists else "legacy_unknown",
                        )
                    )
                    status = "duplicate" if exists else "ingested"
                else:
                    # An exact canonical re-import can establish the previously
                    # unknown source identity, but cannot rewrite its receipt.
                    if receipt["source_key"].startswith("legacy:"):
                        connection.execute(
                            receipts.update()
                            .where(receipts.c.conversation_id == cid)
                            .values(
                                source_key=source_key,
                                content_digest=cid.removeprefix("import_"),
                            )
                        )
                    status = "duplicate"
            records.append(
                {
                    "id": cid,
                    "source_key": source_key,
                    "status": status,
                    "content_digest": cid.removeprefix("import_"),
                }
            )
    ingested = sum(row["status"] == "ingested" for row in records)
    forgotten = sum(row["status"] == "forgotten" for row in records)
    duplicates = len(records) - ingested - forgotten
    return {
        "success": True,
        "ingested": ingested,
        "skipped": duplicates + forgotten,
        "duplicates": duplicates,
        "forgotten": forgotten,
        "pending_indexing": ingested,
        "total_processed": len(records),
        "records": records,
        "message": f"Imported {ingested} conversation(s); {duplicates} duplicate(s) skipped; {forgotten} forgotten source(s) blocked. Indexing pending.",
    }


def forget(conversation_id, *, actor=None, engine):
    deleted_by, _ = importer_provenance(actor, "unattributed")
    sources, receipts, transcripts = (
        ConversationSource.__table__,
        ConversationReceipt.__table__,
        ConversationItem.__table__,
    )
    with transaction(engine) as connection:
        receipt = (
            connection.execute(
                select(receipts).where(receipts.c.conversation_id == conversation_id)
            )
            .mappings()
            .first()
        )
        if receipt is None:
            row = connection.execute(
                select(transcripts.c.platform).where(
                    transcripts.c.id == conversation_id
                )
            ).first()
            if row is None:
                return False
            register_legacy(connection, conversation_id, row.platform)
            receipt = (
                connection.execute(
                    select(receipts).where(
                        receipts.c.conversation_id == conversation_id
                    )
                )
                .mappings()
                .one()
            )
        now = datetime.now(timezone.utc).isoformat()
        source_key = receipt["source_key"]
        connection.execute(
            update(sources)
            .where(sources.c.key == source_key, sources.c.forgotten_at.is_(None))
            .values(forgotten_at=now, forgotten_by=deleted_by)
        )
        ids = select(receipts.c.conversation_id).where(
            receipts.c.source_key == source_key
        )
        connection.execute(delete(transcripts).where(transcripts.c.id.in_(ids)))
        connection.execute(
            update(receipts)
            .where(receipts.c.source_key == source_key, receipts.c.deleted_at.is_(None))
            .values(deleted_at=now, deleted_by=deleted_by)
        )
    return True


def get_receipt(conversation_id, *, engine):
    with engine.connect() as connection:
        row = (
            connection.execute(
                select(
                    ConversationReceipt.__table__,
                    ConversationSource.__table__.c.upstream_id,
                    ConversationSource.__table__.c.identity_kind,
                )
                .join(
                    ConversationSource.__table__,
                    ConversationReceipt.source_key == ConversationSource.key,
                )
                .where(ConversationReceipt.conversation_id == conversation_id)
            )
            .mappings()
            .first()
        )
        return dict(row) if row else {"provenance": "legacy_unknown"}
