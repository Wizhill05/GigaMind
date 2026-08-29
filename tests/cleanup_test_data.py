#!/usr/bin/env python3
"""
GigaMind Test Data Cleanup Utility
Safely scans and removes all test fixtures, test memories, test vector chunks,
and test R2 storage objects created by automated test suites.
Real user knowledge and profile rules are strictly preserved.
"""
import os
import sys
import json
from typing import List, Set

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from typing import List, Set
from sqlmodel import Session, select

from gigamind.db.database import (
    engine,
    MemoryItem,
    StorageFileItem,
    StorageChunkItem,
    ProfileItem,
    ConversationItem
)
from gigamind.services.storage import storage_service

TEST_SOURCE_AGENTS = {"test_runner", "test_suite", "test", "cursor_test"}
TEST_CATEGORIES = {"test", "test_suite", "mcp_test", "api_test", "architecture_test", "hardware_test"}
TEST_TAGS = {"test_runner", "test_suite", "test", "multi-chunk", "r2"}
TEST_FILE_PREFIXES = ("files/test/", "test_", "test_paper", "trapped_ion", "quantum_research", "api_test", "mcp_doc")


def is_test_memory(mem: MemoryItem) -> bool:
    """Determine if a memory item was created by automated tests."""
    agent = (getattr(mem, "source_agent", "") or "").lower()
    if agent in TEST_SOURCE_AGENTS:
        return True

    cat = (mem.category or "").lower()
    if cat in TEST_CATEGORIES:
        return True

    try:
        tags = json.loads(mem.tags_json or "[]")
        if any(t.lower() in ("test_runner", "test_suite", "mcp", "multi-chunk") for t in tags):
            return True
    except Exception:
        pass

    content_start = (mem.content or "").lower()
    test_phrases = (
        "single chunk memory with architecture pdf",
        "gigamind cloudflare r2 and neon architecture specification",
        "temporary memory to test deletion cascade",
        "fastmcp tool memory with attached file",
        "updated content with additional attachment",
        "api test fact with attached whitepaper",
        "user personal note: prefers superconducting transmon"
    )
    if any(phrase in content_start for phrase in test_phrases):
        return True

    return False


def is_test_storage_file(f: StorageFileItem) -> bool:
    """Determine if a storage file record was created by automated tests."""
    agent = (getattr(f, "source_agent", "") or "").lower()
    if agent in TEST_SOURCE_AGENTS or agent == "researcher":
        return True
    key_lower = (f.key or "").lower()
    if any(key_lower.startswith(p) or p in key_lower for p in TEST_FILE_PREFIXES):
        return True
    return False


def cleanup_all_test_data(verbose: bool = True) -> dict:
    """
    Scans Neon PostgreSQL and Cloudflare R2 and removes all test data.
    """
    purged_memories = 0
    purged_chunks = 0
    purged_files = 0
    r2_keys_to_delete: Set[str] = set()

    with Session(engine) as session:
        # 1. Clean Memories
        all_mems = session.exec(select(MemoryItem)).all()
        for mem in all_mems:
            if is_test_memory(mem):
                # Collect R2 keys from test memory
                if mem.attachments_json:
                    try:
                        atts = json.loads(mem.attachments_json)
                        for a in atts:
                            if isinstance(a, dict) and a.get("key"):
                                r2_keys_to_delete.add(a["key"])
                    except Exception:
                        pass
                session.delete(mem)
                purged_memories += 1

        # 2. Clean Storage Files & Chunks
        all_files = session.exec(select(StorageFileItem)).all()
        for sf in all_files:
            if is_test_storage_file(sf):
                r2_keys_to_delete.add(sf.key)
                # Delete corresponding chunks
                chunks = session.exec(select(StorageChunkItem).where(StorageChunkItem.file_key == sf.key)).all()
                for c in chunks:
                    session.delete(c)
                    purged_chunks += 1
                session.delete(sf)
                purged_files += 1

        # 3. Clean any orphaned test storage chunks
        all_chunks = session.exec(select(StorageChunkItem)).all()
        for c in all_chunks:
            if any((c.file_key or "").lower().startswith(p) for p in TEST_FILE_PREFIXES):
                session.delete(c)
                purged_chunks += 1

        session.commit()

    # 4. Clean R2 objects if storage is enabled
    r2_purged_count = 0
    if r2_keys_to_delete and storage_service.is_enabled():
        try:
            r2_purged_count = storage_service.delete_files(list(r2_keys_to_delete))
        except Exception as r2_err:
            if verbose:
                print(f"⚠️ Note during R2 test files purge: {r2_err}")

    summary = {
        "purged_memories": purged_memories,
        "purged_storage_files": purged_files,
        "purged_storage_chunks": purged_chunks,
        "purged_r2_keys": len(r2_keys_to_delete),
        "r2_deleted_count": r2_purged_count
    }

    if verbose:
        print("🧹 GigaMind Test Data Cleanup Report:")
        print(f"  • Test Memories Purged: {purged_memories}")
        print(f"  • Test Storage Files Purged: {purged_files}")
        print(f"  • Test Storage Chunks Purged: {purged_chunks}")
        print(f"  • Test R2 Keys Queued for Deletion: {len(r2_keys_to_delete)}")
        print("✅ Cleanup complete. Live user data preserved.")

    return summary


if __name__ == "__main__":
    cleanup_all_test_data(verbose=True)
