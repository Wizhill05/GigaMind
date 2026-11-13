"""Import receipts contain identifiers and hashes, never transcript snapshots."""

from typing import Optional
from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


class ConversationSource(SQLModel, table=True):
    __tablename__ = "conversation_sources"
    key: str = Field(primary_key=True)
    platform: str
    upstream_id: Optional[str] = None
    identity_kind: str
    created_at: str
    forgotten_at: Optional[str] = None
    forgotten_by: Optional[str] = None


class ConversationReceipt(SQLModel, table=True):
    __tablename__ = "conversation_receipts"
    conversation_id: str = Field(primary_key=True)
    source_key: str = Field(foreign_key="conversation_sources.key", index=True)
    content_digest: Optional[str] = None
    imported_at: Optional[str] = None
    imported_by: Optional[str] = None
    provenance: str
    deleted_at: Optional[str] = None
    deleted_by: Optional[str] = None


def register_legacy(connection, conversation_id, platform):
    """Backfill unknown attribution without inventing an upstream identity."""
    sources, receipts = ConversationSource.__table__, ConversationReceipt.__table__
    source_key = "legacy:" + conversation_id
    connection.execute(
        sources.insert().values(
            key=source_key,
            platform=platform,
            identity_kind="legacy_unknown",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    )
    connection.execute(
        receipts.insert().values(
            conversation_id=conversation_id,
            source_key=source_key,
            provenance="legacy_unknown",
        )
    )
