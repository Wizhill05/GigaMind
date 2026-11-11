import os
import json
import uuid
from datetime import datetime, timezone
from typing import Optional, List
from dotenv import load_dotenv
from sqlmodel import SQLModel, Field, create_engine, Session, select, text

# Load environment variables from .env
load_dotenv()
# Models
class ProfileItem(SQLModel, table=True):
    __tablename__ = "profile"
    id: str = Field(primary_key=True)
    category: str = Field(default="general", index=True)
    key: str = Field(unique=True, index=True)
    value: str
    source_agent: str = Field(default="user", index=True) # e.g. claude, gpt, gemini, user, system
    updated_at: str

class MemoryItem(SQLModel, table=True):
    __tablename__ = "memories"
    id: str = Field(primary_key=True)
    content: str
    category: str = Field(default="general", index=True)
    media_type: str = Field(default="text", index=True) # text, image, pdf, code
    media_url: Optional[str] = Field(default=None)
    source_agent: str = Field(default="user", index=True) # e.g. claude, gpt, gemini, user, system
    tags_json: str = Field(default="[]")
    embedding_json: str = Field(default="[]")
    attachments_json: str = Field(default="[]")
    parent_id: Optional[str] = Field(default=None, index=True)
    chunk_index: Optional[int] = Field(default=None)
    total_chunks: Optional[int] = Field(default=None)
    created_at: str
    last_accessed: str

class ConversationItem(SQLModel, table=True):
    __tablename__ = "conversations"
    id: str = Field(primary_key=True)
    platform: str = Field(index=True)
    title: str
    summary: str
    source_agent: str = Field(default="user", index=True) # e.g. claude, gpt, gemini, user, system
    messages_json: str = Field(default="[]")
    embedding_json: str = Field(default="[]")
    created_at: str

class TaskSessionItem(SQLModel, table=True):
    __tablename__ = "task_sessions"
    id: str = Field(primary_key=True)
    task_name: str = Field(index=True)
    summary: str
    status: str = Field(default="active")
    source_agent: str = Field(default="user", index=True)
    updated_at: str

class StorageFileItem(SQLModel, table=True):
    __tablename__ = "storage_files"
    id: str = Field(primary_key=True)
    key: str = Field(unique=True, index=True)
    filename: str
    mime_type: Optional[str] = Field(default="application/octet-stream")
    multimodal_type: str = Field(default="text", index=True) # pdf, image, markdown, code, binary
    size_bytes: int = Field(default=0)
    source_agent: str = Field(default="user", index=True)
    extracted_text_length: int = Field(default=0)
    total_chunks: int = Field(default=0)
    indexing_status: str = Field(default="completed", index=True) # pending, completed, failed, unsupported
    document_summary: Optional[str] = Field(default=None)
    embedding_json: str = Field(default="[]")
    created_at: str
    updated_at: str

class StorageChunkItem(SQLModel, table=True):
    __tablename__ = "storage_chunks"
    id: str = Field(primary_key=True)
    file_id: str = Field(index=True)
    file_key: str = Field(index=True)
    filename: str
    chunk_index: int = Field(default=0, index=True)
    total_chunks: int = Field(default=1)
    page_number: Optional[int] = Field(default=None, index=True)
    is_visual_anchor: bool = Field(default=False)
    content: str
    embedding_json: str = Field(default="[]")
    created_at: str
# Database Engine initialization with automatic fallback
raw_db_url = os.getenv("DATABASE_URL")
if raw_db_url and raw_db_url.startswith("postgres://"):
    raw_db_url = raw_db_url.replace("postgres://", "postgresql://", 1)
if raw_db_url and raw_db_url.startswith("postgresql://"):
    raw_db_url = raw_db_url.replace("postgresql://", "postgresql+psycopg2://", 1)

def get_db_engine():
    global raw_db_url
    env_name = os.getenv("ENVIRONMENT", "development").lower()
    is_production = env_name in ("production", "prod") or bool(os.getenv("RENDER"))

    if raw_db_url and raw_db_url.startswith("postgresql"):
        try:
            # Ensure sslmode=require for Neon / remote Postgres if not specified
            conn_url = raw_db_url
            if "neon.tech" in conn_url and "sslmode=" not in conn_url:
                separator = "&" if "?" in conn_url else "?"
                conn_url = f"{conn_url}{separator}sslmode=require"
            pg_engine = create_engine(conn_url, pool_pre_ping=True)
            with pg_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            print("⚡ Connected successfully to Neon PostgreSQL (Lakebase Postgres).")
            return pg_engine, True
        except Exception as e:
            if is_production:
                raise RuntimeError(
                    f"❌ CRITICAL ERROR: Failed to connect to Neon PostgreSQL in production ({e}). "
                    "Refusing silent fallback to ephemeral SQLite on Render (which erases all data on redeploy). "
                    "Please check your Neon database status and verify DATABASE_URL in Render Dashboard Environment Variables."
                ) from e
            print(f"⚠️ Neon PostgreSQL connection failed ({e}). Falling back to local SQLite database for development.")
    elif is_production:
        raise RuntimeError(
            "❌ CRITICAL ERROR: DATABASE_URL environment variable is required in production! "
            "Render web services use ephemeral storage and do not persist SQLite databases across redeploys. "
            "Please configure DATABASE_URL (Neon PostgreSQL connection string) in your Render Dashboard Environment Variables."
        )

    db_path = os.getenv("DB_PATH", "./gigamind.db")
    sqlite_url = f"sqlite:///{db_path}"
    sqlite_engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})
    return sqlite_engine, False
engine, is_postgres = get_db_engine()

def init_db():
    from gigamind.db.migrations import migrate
    migrate(engine)
    print(f"✅ GigaMind database initialized on {'PostgreSQL' if is_postgres else 'SQLite'}.")

def get_session():
    with Session(engine) as session:
        yield session
