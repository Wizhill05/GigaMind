"""Content-free source attribution tables."""
from typing import Optional
from sqlmodel import Field, SQLModel


class SourceHead(SQLModel, table=True):
    __tablename__ = "source_provenance_heads"
    kind: str = Field(primary_key=True)
    source_id: str = Field(primary_key=True)
    revision: int = 0
    active: bool = True
    creator_id: Optional[str] = None
    creator_provenance: str


class SourceReceipt(SQLModel, table=True):
    __tablename__ = "source_provenance_receipts"
    kind: str = Field(primary_key=True)
    source_id: str = Field(primary_key=True)
    revision: int = Field(primary_key=True)
    operation: str
    writer_id: Optional[str] = None
    writer_provenance: str
    payload_hash: Optional[str] = None
    source_revision: Optional[str] = None
    timestamp: str
