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
    created_at: str
    last_accessed: str

class ConversationItem(SQLModel, table=True):
    __tablename__ = "conversations"
    id: str = Field(primary_key=True)
    platform: str = Field(index=True)
    title: str
    summary: str
    source_agent: str = Field(default="user", index=True) # e.g. claude, gpt, gemini, user, system
    messages_json: str
    embedding_json: str
    created_at: str

class TaskSessionItem(SQLModel, table=True):
    __tablename__ = "task_sessions"
    id: str = Field(primary_key=True)
    task_name: str = Field(index=True)
    summary: str
    status: str = Field(default="active")
    source_agent: str = Field(default="user", index=True)
    updated_at: str

# Database Engine initialization with automatic fallback
raw_db_url = os.getenv("DATABASE_URL")
if raw_db_url and raw_db_url.startswith("postgres://"):
    raw_db_url = raw_db_url.replace("postgres://", "postgresql://", 1)

def get_db_engine():
    global raw_db_url
    if raw_db_url and raw_db_url.startswith("postgresql"):
        try:
            pg_engine = create_engine(raw_db_url, pool_pre_ping=True)
            with pg_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            print("⚡ Connected successfully to Supabase PostgreSQL.")
            return pg_engine, True
        except Exception as e:
            print(f"⚠️ PostgreSQL connection failed ({e}). Falling back to local SQLite database.")

    db_path = os.getenv("DB_PATH", "./gigamind.db")
    sqlite_url = f"sqlite:///{db_path}"
    sqlite_engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})
    return sqlite_engine, False

engine, is_postgres = get_db_engine()

def init_db():
    if is_postgres:
        try:
            with engine.connect() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                conn.execute(text("ALTER TABLE memories ADD COLUMN IF NOT EXISTS media_type VARCHAR DEFAULT 'text';"))
                conn.execute(text("ALTER TABLE memories ADD COLUMN IF NOT EXISTS media_url VARCHAR;"))
                conn.execute(text("ALTER TABLE memories ADD COLUMN IF NOT EXISTS source_agent VARCHAR DEFAULT 'user';"))
                conn.execute(text("ALTER TABLE profile ADD COLUMN IF NOT EXISTS source_agent VARCHAR DEFAULT 'user';"))
                conn.execute(text("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS source_agent VARCHAR DEFAULT 'user';"))
                conn.execute(text("ALTER TABLE task_sessions ADD COLUMN IF NOT EXISTS source_agent VARCHAR DEFAULT 'user';"))
                conn.commit()
        except Exception as e:
            print(f"pgvector/column migration note: {e}")
    else:
        try:
            with engine.connect() as conn:
                for stmt in [
                    "ALTER TABLE memories ADD COLUMN media_type TEXT DEFAULT 'text';",
                    "ALTER TABLE memories ADD COLUMN media_url TEXT;",
                    "ALTER TABLE memories ADD COLUMN source_agent TEXT DEFAULT 'user';",
                    "ALTER TABLE profile ADD COLUMN source_agent TEXT DEFAULT 'user';",
                    "ALTER TABLE conversations ADD COLUMN source_agent TEXT DEFAULT 'user';",
                    "ALTER TABLE task_sessions ADD COLUMN source_agent TEXT DEFAULT 'user';"
                ]:
                    try:
                        conn.execute(text(stmt))
                        conn.commit()
                    except Exception:
                        pass
        except Exception:
            pass

    SQLModel.metadata.create_all(engine)
    print(f"✅ GigaMind database initialized on {'Supabase PostgreSQL' if is_postgres else 'SQLite'}.")

def get_session():
    with Session(engine) as session:
        yield session
