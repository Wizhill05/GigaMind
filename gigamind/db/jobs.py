from typing import Optional
from sqlmodel import SQLModel, Field


class Job(SQLModel, table=True):
    __tablename__ = "jobs"
    id: str = Field(primary_key=True)
    kind: str
    resource_key: str = Field(index=True)
    payload_json: str
    idempotency_key: Optional[str] = Field(default=None, unique=True)
    state: str = Field(index=True)
    result_json: Optional[str] = None
    error: Optional[str] = None
    attempts: int = 0
    max_attempts: int = 3
    available_at: str
    lease_token: Optional[str] = None
    lease_deadline: Optional[str] = None
    created_at: str
    updated_at: str


class ResourceJobState(SQLModel, table=True):
    __tablename__ = "resource_job_state"
    key: str = Field(primary_key=True)
    current_job_id: Optional[str] = None
    deleted: bool = False
    created_at: str
    updated_at: str
