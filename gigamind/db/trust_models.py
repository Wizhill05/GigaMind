from typing import Optional
from sqlmodel import SQLModel, Field
from sqlalchemy import UniqueConstraint, Index, CheckConstraint, func, text
from sqlalchemy.schema import CreateIndex


class MemoryProposal(SQLModel, table=True):
    __tablename__ = "trust_proposals"
    __table_args__ = (UniqueConstraint("writer_id", "idempotency_key"),)
    id: str = Field(primary_key=True)
    writer_id: str
    idempotency_key: str
    payload_json: str
    project_id: Optional[str] = Field(default=None, index=True)
    revision: int = 1
    status: str = "proposed"
    created_at: str
    updated_at: str


class AcceptedKnowledge(SQLModel, table=True):
    __tablename__ = "trust_knowledge"
    __table_args__ = (
        CheckConstraint("project_id IS NULL OR length(trim(project_id)) > 0"),
        CheckConstraint("subject IS NULL OR length(trim(subject)) > 0"),
    )
    id: str = Field(primary_key=True)
    proposal_id: str
    project_id: Optional[str] = Field(default=None, index=True)
    subject: Optional[str] = Field(default=None, index=True)
    content: str
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    data_json: str
    writer_id: str
    revision: int = 1
    status: str = "accepted"
    created_at: str
    updated_at: str


class KnowledgeRevision(SQLModel, table=True):
    __tablename__ = "trust_revisions"
    __table_args__ = (UniqueConstraint("memory_id", "revision"),)
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
    __tablename__ = "trust_activity"
    id: str = Field(primary_key=True)
    project_id: Optional[str] = Field(default=None, index=True)
    writer_id: str
    action: str
    target_id: str
    revision: int = 1
    status: str = "recorded"
    created_at: str
    updated_at: str


Index(
    "uq_trust_accepted_project_subject",
    func.coalesce(AcceptedKnowledge.__table__.c.project_id, ""),
    AcceptedKnowledge.__table__.c.subject,
    unique=True,
    sqlite_where=text("status = 'accepted' AND subject IS NOT NULL"),
    postgresql_where=text("status = 'accepted' AND subject IS NOT NULL"),
)


def initialize_trust_tables(engine):
    SQLModel.metadata.create_all(
        engine,
        tables=[
            cls.__table__
            for cls in (
                MemoryProposal,
                AcceptedKnowledge,
                KnowledgeRevision,
                ActivityEvent,
            )
        ],
    )
    # create_all skips indexes on existing tables, so upgrades need this step too.
    with engine.begin() as connection:
        for index in AcceptedKnowledge.__table__.indexes:
            if index.name == "uq_trust_accepted_project_subject":
                connection.execute(CreateIndex(index, if_not_exists=True))
