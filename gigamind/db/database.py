import os
import json
from datetime import datetime, timezone
from typing import Optional, List
from sqlmodel import SQLModel, Field, create_engine, Session, select, text

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

# Database Engine initialization (Supports Supabase Postgres + SQLite)
database_url = os.getenv("DATABASE_URL")
if not database_url:
    db_path = os.getenv("DB_PATH", "./gigamind.db")
    database_url = f"sqlite:///{db_path}"

if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

is_postgres = database_url.startswith("postgresql")
connect_args = {"check_same_thread": False} if not is_postgres else {}
engine = create_engine(database_url, connect_args=connect_args)

def init_db():
    if is_postgres:
        try:
            with engine.connect() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                conn.commit()
                print("⚡ Supabase pgvector extension verified.")
        except Exception as e:
            print(f"PostgreSQL extension setup note: {e}")

    SQLModel.metadata.create_all(engine)
    print(f"✅ GigaMind database initialized on {'Supabase PostgreSQL' if is_postgres else 'SQLite'}.")

def get_session():
    with Session(engine) as session:
        yield session
