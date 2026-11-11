from typing import Optional
from sqlalchemy import UniqueConstraint
from sqlmodel import SQLModel, Field


class Handoff(SQLModel, table=True):
    __tablename__ = 'coordination_handoffs'
    __table_args__ = (UniqueConstraint('writer_id', 'idempotency_key'),)
    id: str = Field(primary_key=True)
    writer_id: str
    idempotency_key: str
    project_id: Optional[str] = Field(default=None, index=True)
    payload_json: str
    status: str
    revision: int = 1
    created_at: str
    updated_at: str


class MemoryIssue(SQLModel, table=True):
    __tablename__ = 'coordination_issues'
    __table_args__ = (UniqueConstraint('writer_id', 'idempotency_key'),)
    id: str = Field(primary_key=True)
    writer_id: str
    idempotency_key: str
    project_id: Optional[str] = Field(default=None, index=True)
    memory_id: str
    payload_json: str
    status: str = 'open'
    revision: int = 1
    created_at: str
    updated_at: str
