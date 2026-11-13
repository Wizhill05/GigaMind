from typing import Optional

from sqlmodel import Field, SQLModel


class ConversationIndexState(SQLModel, table=True):
    __tablename__ = "conversation_index_state"
    conversation_id: str = Field(primary_key=True)
    current_job_id: Optional[str] = None
    requested_fingerprint: Optional[str] = None
    indexed_fingerprint: Optional[str] = None
    model: Optional[str] = None
    dimension: Optional[int] = None
    segment_count: int = 0
    updated_at: str


class ConversationIndexSegment(SQLModel, table=True):
    __tablename__ = "conversation_index_segments"
    conversation_id: str = Field(primary_key=True)
    segment_index: int = Field(primary_key=True)
    content: str
    embedding_json: str
