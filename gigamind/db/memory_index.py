from typing import Optional
from sqlmodel import SQLModel, Field


class MemoryIndexState(SQLModel, table=True):
    __tablename__ = "memory_index_state"
    memory_id: str = Field(primary_key=True)
    revision: int = 1
    index_status: str = "pending"
    index_error: Optional[str] = None
    embedding_model: Optional[str] = None
    embedding_dimension: Optional[int] = None
    indexed_revision: Optional[int] = None
    created_at: str
    updated_at: str
