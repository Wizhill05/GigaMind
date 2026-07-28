import os
import json
from datetime import datetime, timezone
from typing import Optional, List
from sqlmodel import SQLModel, Field, create_engine, Session, select

# Models
class ProfileItem(SQLModel, table=True):
    __tablename__ = "profile"
    id: str = Field(primary_key=True)
    category: str = Field(default="general", index=True)
    key: str = Field(unique=True, index=True)
    value: str
    updated_at: str

class MemoryItem(SQLModel, table=True):
    __tablename__ = "memories"
    id: str = Field(primary_key=True)
    content: str
    category: str = Field(default="general", index=True)
    media_type: str = Field(default="text", index=True) # text, image, pdf, code
    media_url: Optional[str] = Field(default=None)
    tags_json: str = Field(default="[]")
    embedding_json: str = Field(default="[]")
    created_at: str
    last_accessed: str

class ConversationItem(SQLModel, table=True):
    __tablename__ = "conversations"
    id: str = Field(primary_key=True)
    platform: str = Field(index=True)
    title: str
    summary: str
    messages_json: str
    embedding_json: str
    created_at: str

class TaskSessionItem(SQLModel, table=True):
    __tablename__ = "task_sessions"
    id: str = Field(primary_key=True)
    task_name: str = Field(index=True)
    summary: str
    status: str = Field(default="active")
    updated_at: str

# Database Engine initialization
database_url = os.getenv("DATABASE_URL")
if not database_url:
    db_path = os.getenv("DB_PATH", "./gigamind.db")
    database_url = f"sqlite:///{db_path}"

if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
engine = create_engine(database_url, connect_args=connect_args)

def init_db():
    SQLModel.metadata.create_all(engine)
    print("✅ GigaMind SQLModel database initialized successfully.")

def get_session():
    with Session(engine) as session:
        yield session
