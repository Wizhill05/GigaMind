from typing import Optional
from sqlmodel import SQLModel, Field
from sqlalchemy import UniqueConstraint

class MemoryProposal(SQLModel, table=True):
    __tablename__ = 'trust_proposals'
    __table_args__ = (UniqueConstraint('writer_id', 'idempotency_key'),)
    id: str = Field(primary_key=True)
    writer_id: str
    idempotency_key: str
    payload_json: str
    project_id: Optional[str] = Field(default=None, index=True)
    revision: int = 1
    status: str = 'proposed'
    created_at: str
    updated_at: str

class AcceptedKnowledge(SQLModel, table=True):
    __tablename__ = 'trust_knowledge'
    id: str = Field(primary_key=True)
    proposal_id: str
    project_id: Optional[str] = Field(default=None, index=True)
    subject: Optional[str] = Field(default=None, index=True)
    content: str
    data_json: str
    writer_id: str
    revision: int = 1
    status: str = 'accepted'
    created_at: str
    updated_at: str

class KnowledgeRevision(SQLModel, table=True):
    __tablename__ = 'trust_revisions'
    __table_args__ = (UniqueConstraint('memory_id', 'revision'),)
    id: str = Field(primary_key=True)
    memory_id: str = Field(index=True)
    project_id: Optional[str] = None
    revision: int
    status: str
    snapshot_json: str
    writer_id: str
    created_at: str
    updated_at: str

class ActivityEvent(SQLModel, table=True):
    __tablename__ = 'trust_activity'
    id: str = Field(primary_key=True)
    project_id: Optional[str] = Field(default=None, index=True)
    writer_id: str
    action: str
    target_id: str
    revision: int = 1
    status: str = 'recorded'
    created_at: str
    updated_at: str

def initialize_trust_tables(engine):
    SQLModel.metadata.create_all(engine, tables=[cls.__table__ for cls in (MemoryProposal, AcceptedKnowledge, KnowledgeRevision, ActivityEvent)])
