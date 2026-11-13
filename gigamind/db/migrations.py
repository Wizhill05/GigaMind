"""Transactional schema upgrades for databases created by earlier releases."""

import json
import os
import uuid
from datetime import datetime, timezone
import pgvector.sqlalchemy  # Register vector types for schema inspection.

from sqlalchemy import inspect, text
from sqlalchemy.schema import CreateIndex
from sqlmodel import SQLModel

from gigamind.db import trust_models  # register trust tables
from gigamind.db.jobs import UploadManifest
from gigamind.db.coordination import Handoff, MemoryIssue

from gigamind.db.conversation_ledger import (
    ConversationSource,
    ConversationReceipt,
    register_legacy,
)

VERSION = 6
LEGACY_COLUMNS = {
    "memories": {
        "media_type": "TEXT DEFAULT 'text'",
        "media_url": "TEXT",
        "source_agent": "TEXT DEFAULT 'user'",
        "parent_id": "TEXT",
        "chunk_index": "INTEGER",
        "total_chunks": "INTEGER",
        "attachments_json": "TEXT DEFAULT '[]'",
    },
    "profile": {"source_agent": "TEXT DEFAULT 'user'"},
    "conversations": {"source_agent": "TEXT DEFAULT 'user'"},
    "task_sessions": {"source_agent": "TEXT DEFAULT 'user'"},
    "storage_files": {
        "multimodal_type": "TEXT DEFAULT 'text'",
        "document_summary": "TEXT",
        "embedding_json": "TEXT DEFAULT '[]'",
    },
    "storage_chunks": {"is_visual_anchor": "BOOLEAN DEFAULT FALSE"},
}
VECTOR_TABLES = ("memories", "storage_chunks", "storage_files", "conversations")


def _current_schema(conn):
    if conn.dialect.name == "postgresql":
        return conn.execute(text("SELECT current_schema()")).scalar_one()
    return None


def schema_version(engine):
    with engine.connect() as conn:
        if not inspect(conn).has_table(
            "schema_migrations", schema=_current_schema(conn)
        ):
            return 0
        return conn.execute(
            text("SELECT COALESCE(MAX(version), 0) FROM schema_migrations")
        ).scalar_one()


def schema_ready(engine):
    with engine.connect() as conn:
        inspector = inspect(conn)
        schema = _current_schema(conn)
        if not inspector.has_table("schema_migrations", schema=schema):
            return False
        if (
            conn.execute(
                text("SELECT COALESCE(MAX(version), 0) FROM schema_migrations")
            ).scalar_one()
            != VERSION
        ):
            return False
        for table in SQLModel.metadata.sorted_tables:
            if not inspector.has_table(table.name, schema=table.schema or schema):
                return False
            if not {c.name for c in table.columns}.issubset(
                {
                    c["name"]
                    for c in inspector.get_columns(
                        table.name, schema=table.schema or schema
                    )
                }
            ):
                return False
        if conn.dialect.name == "sqlite":
            indexes = {
                r[1]
                for r in conn.exec_driver_sql('PRAGMA index_list("trust_knowledge")')
            }
        else:
            indexes = {
                i["name"]
                for i in inspector.get_indexes("trust_knowledge", schema=schema)
            }
        if "uq_trust_accepted_project_subject" not in indexes:
            return False
        if conn.dialect.name == "postgresql":
            try:
                dimension = int(os.getenv("EMBEDDING_DIM", "768"))
            except ValueError:
                return False
            if not 1 <= dimension <= 2000:
                return False
            for table in VECTOR_TABLES:
                column = conn.execute(
                    text("""SELECT a.atttypmod, t.typname
                    FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
                    JOIN pg_namespace n ON n.oid=c.relnamespace
                    JOIN pg_type t ON t.oid=a.atttypid
                    WHERE n.nspname=current_schema() AND c.relname=:table
                    AND a.attname='embedding_vector' AND NOT a.attisdropped"""),
                    {"table": table},
                ).first()
                if not column or column[0] != dimension or column[1] != "vector":
                    return False
                valid_index = conn.execute(
                    text("""SELECT EXISTS (
                    SELECT 1 FROM pg_index i JOIN pg_class idx ON idx.oid=i.indexrelid
                    JOIN pg_namespace n ON n.oid=idx.relnamespace
                    JOIN pg_am am ON am.oid=idx.relam
                    WHERE n.nspname=current_schema() AND idx.relname=:index
                    AND i.indisvalid AND am.amname='hnsw')"""),
                    {"index": f"{table}_embedding_hnsw_idx"},
                ).scalar_one()
                if not valid_index:
                    return False
        return True


def _backfill(conn):
    last = ""
    while True:
        rows = (
            conn.execute(
                text(
                    "SELECT id, attachments_json, media_url, media_type, source_agent, created_at FROM memories WHERE id > :last ORDER BY id LIMIT 200"
                ),
                {"last": last},
            )
            .mappings()
            .all()
        )
        if not rows:
            break
        for row in rows:
            last = row["id"]
            try:
                attachments = json.loads(row["attachments_json"] or "[]")
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Invalid attachments JSON for memory {last}") from exc
            if not isinstance(attachments, list) or any(
                not isinstance(att, dict) for att in attachments
            ):
                raise ValueError(f"Invalid attachment list for memory {last}")
            if not attachments and row["media_url"]:
                attachments = [
                    {"key": row["media_url"], "mime_type": row["media_type"]}
                ]
            for att in attachments:
                key = att.get("key")
                if not key:
                    continue
                if not isinstance(key, str):
                    raise ValueError(f"Invalid attachment key for memory {last}")
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    text(
                        """INSERT INTO storage_files (id, key, filename, mime_type, multimodal_type, size_bytes, source_agent, extracted_text_length, total_chunks, indexing_status, embedding_json, created_at, updated_at)
                    VALUES (:id, :key, :filename, :mime, 'text', :size, :source, 0, 0, 'pending', '[]', :created, :updated) ON CONFLICT (key) DO NOTHING"""
                    ),
                    {
                        "id": "file_" + uuid.uuid4().hex,
                        "key": key,
                        "filename": att.get("filename") or key.split("/")[-1],
                        "mime": att.get("mime_type") or "application/octet-stream",
                        "size": att.get("size_bytes", 0),
                        "source": row["source_agent"] or "user",
                        "created": row["created_at"] or now,
                        "updated": now,
                    },
                )


def _upgrade(conn):
    inspector = inspect(conn)
    schema = _current_schema(conn)
    for table, columns in LEGACY_COLUMNS.items():
        if not inspector.has_table(table, schema=schema):
            continue
        existing = {c["name"] for c in inspector.get_columns(table, schema=schema)}
        for name, ddl in columns.items():
            if name not in existing:
                conn.exec_driver_sql(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {ddl}')
    if conn.dialect.name == "postgresql":
        conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
    SQLModel.metadata.create_all(conn)
    if conn.dialect.name == "postgresql":
        dimension = int(os.getenv("EMBEDDING_DIM", "768"))
        if not 1 <= dimension <= 2000:
            raise ValueError(
                "EMBEDDING_DIM must be between 1 and 2000 for HNSW indexes"
            )
        for table in VECTOR_TABLES:
            typmod = conn.execute(
                text(
                    """SELECT a.atttypmod FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=current_schema() AND c.relname=:table AND a.attname='embedding_vector' AND NOT a.attisdropped"""
                ),
                {"table": table},
            ).scalar_one_or_none()
            if typmod is None:
                conn.exec_driver_sql(
                    f'ALTER TABLE "{table}" ADD COLUMN embedding_vector vector({dimension})'
                )
            elif typmod != dimension:
                raise RuntimeError(
                    f"{table}.embedding_vector has dimension {typmod}; configured EMBEDDING_DIM is {dimension}. Reindex or migrate embeddings before changing dimensions."
                )
            conn.exec_driver_sql(
                f'CREATE INDEX IF NOT EXISTS {table}_embedding_hnsw_idx ON "{table}" USING hnsw (embedding_vector vector_cosine_ops) WITH (m = 16, ef_construction = 64)'
            )
    for table in SQLModel.metadata.sorted_tables:
        for index in table.indexes:
            conn.execute(CreateIndex(index, if_not_exists=True))
    _backfill(conn)


def _upgrade_conversation_ledger(conn):
    from gigamind.db.database import ConversationItem
    from sqlalchemy import select

    ConversationSource.__table__.create(conn, checkfirst=True)
    ConversationReceipt.__table__.create(conn, checkfirst=True)
    rows = conn.execute(
        select(ConversationItem.id, ConversationItem.platform)
        .where(
            ~select(ConversationReceipt.conversation_id)
            .where(ConversationReceipt.conversation_id == ConversationItem.id)
            .exists()
        )
        .execution_options(yield_per=500)
    )
    for row in rows:
        register_legacy(conn, row.id, row.platform)


def migrate(engine):
    with engine.connect() as conn:
        if conn.dialect.name == "sqlite":
            conn.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            conn.begin()
            conn.exec_driver_sql("SELECT pg_advisory_xact_lock(723649821)")
        try:
            schema = _current_schema(conn)
            if schema is not None:
                conn.execution_options(schema_translate_map={None: schema})
            conn.exec_driver_sql(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)"
            )
            version = conn.execute(
                text("SELECT COALESCE(MAX(version), 0) FROM schema_migrations")
            ).scalar_one()
            if version > VERSION:
                raise RuntimeError(
                    f"Database schema version {version} is newer than supported version {VERSION}"
                )
            if version < 1:
                _upgrade(conn)
            if version < 2 and inspect(conn).has_table(
                "client_credentials", schema=schema
            ):
                columns = {
                    c["name"]
                    for c in inspect(conn).get_columns(
                        "client_credentials", schema=schema
                    )
                }
                for name, ddl in {
                    "created_at": "TEXT",
                    "expires_at": "TEXT",
                    "last_used_at": "TEXT",
                    "revision": "INTEGER NOT NULL DEFAULT 0",
                }.items():
                    if name not in columns:
                        conn.exec_driver_sql(
                            f'ALTER TABLE client_credentials ADD COLUMN "{name}" {ddl}'
                        )
            if version < 3:
                UploadManifest.__table__.create(conn, checkfirst=True)
            if version < 4:
                Handoff.__table__.create(conn, checkfirst=True)
                MemoryIssue.__table__.create(conn, checkfirst=True)
            if version < 5:
                columns = {
                    c["name"]
                    for c in inspect(conn).get_columns("trust_knowledge", schema=schema)
                }
                for name in ("valid_from", "valid_until"):
                    if name not in columns:
                        conn.exec_driver_sql(
                            f'ALTER TABLE trust_knowledge ADD COLUMN "{name}" TEXT'
                        )
            if version < 6:
                _upgrade_conversation_ledger(conn)
            if version < VERSION:
                conn.execute(
                    text("INSERT INTO schema_migrations (version) VALUES (:version)"),
                    {"version": VERSION},
                )
            # New modules may register tables during the same upgrade as a versioned step.
            missing = [
                t
                for t in SQLModel.metadata.sorted_tables
                if not inspect(conn).has_table(t.name, schema=t.schema or schema)
            ]
            if missing:
                SQLModel.metadata.create_all(conn, tables=missing)
            for table in SQLModel.metadata.sorted_tables:
                actual = {
                    c["name"]
                    for c in inspect(conn).get_columns(
                        table.name, schema=table.schema or schema
                    )
                }
                missing_columns = {c.name for c in table.columns} - actual
                if missing_columns:
                    raise RuntimeError(
                        f"{table.name} is missing columns: {sorted(missing_columns)}"
                    )
            for table in SQLModel.metadata.sorted_tables:
                for index in table.indexes:
                    conn.execute(CreateIndex(index, if_not_exists=True))
            if conn.dialect.name == "postgresql":
                dimension = int(os.getenv("EMBEDDING_DIM", "768"))
                if not 1 <= dimension <= 2000:
                    raise ValueError(
                        "EMBEDDING_DIM must be between 1 and 2000 for HNSW indexes"
                    )
                for table in VECTOR_TABLES:
                    result = conn.execute(
                        text(
                            """SELECT a.atttypmod, t.typname FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_type t ON t.oid=a.atttypid WHERE n.nspname=current_schema() AND c.relname=:table AND a.attname='embedding_vector' AND NOT a.attisdropped"""
                        ),
                        {"table": table},
                    ).first()
                    if not result or result[1] != "vector" or result[0] != dimension:
                        raise RuntimeError(
                            f"{table}.embedding_vector is incompatible with EMBEDDING_DIM={dimension}; migrate or reindex embeddings before starting"
                        )
                    conn.exec_driver_sql(
                        f'CREATE INDEX IF NOT EXISTS {table}_embedding_hnsw_idx ON "{table}" USING hnsw (embedding_vector vector_cosine_ops) WITH (m = 16, ef_construction = 64)'
                    )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    if not schema_ready(engine):
        raise RuntimeError(
            "Database schema is incomplete; repair the schema before starting"
        )
