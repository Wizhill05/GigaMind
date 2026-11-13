"""Read-only, bounded inspection of evidence against current local records."""

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import func, cast, LargeBinary, case
from sqlmodel import Session, select

from gigamind.db.database import MemoryItem, ConversationItem, StorageChunkItem
from gigamind.db.jobs import ResourceJobState
from gigamind.db.memory_index import MemoryIndexState
from gigamind.db.trust_models import MemoryProposal
from gigamind.services import trust

MAX_SOURCE = 100_000
MAX_REQUEST = 1_000_000


def _load(session, kind, source_id, budget):
    model, column = {
        "memory": (MemoryItem, MemoryItem.content),
        "conversation": (ConversationItem, ConversationItem.messages_json),
        "file_chunk": (StorageChunkItem, StorageChunkItem.content),
    }[kind]
    byte_length = (
        func.octet_length(column)
        if session.bind.dialect.name == "postgresql"
        else func.length(cast(column, LargeBinary))
    )
    allowance = min(MAX_SOURCE, budget)
    content = case((byte_length <= allowance, column), else_=None)
    statement = select(byte_length, content).where(model.id == source_id)
    locator = {"message_index": None, "page_number": None, "chunk_index": None}
    if kind == "memory":
        statement = statement.add_columns(MemoryIndexState.revision).outerjoin(
            MemoryIndexState, MemoryIndexState.memory_id == MemoryItem.id
        )
    elif kind == "file_chunk":
        statement = statement.add_columns(
            StorageChunkItem.page_number, StorageChunkItem.chunk_index
        ).where(
            ~select(ResourceJobState.key)
            .where(
                ResourceJobState.key == StorageChunkItem.file_key,
                ResourceJobState.deleted.is_(True),
            )
            .exists()
        )
    row = session.exec(statement).first()
    if row is None:
        return None
    if kind == "file_chunk":
        locator.update(page_number=row[2], chunk_index=row[3])
    return row[0], row[1], locator, row[2] if kind == "memory" else None


def inspect(actor, proposal_id, expected_revision):
    trust.admin(actor)
    with Session(trust.engine) as session:
        proposal = session.get(MemoryProposal, proposal_id)
        if proposal is None:
            trust.fail(404, "Proposal not found")
        if proposal.revision != expected_revision:
            trust.fail(409, "Stale proposal revision")
        evidence = json.loads(proposal.payload_json)["evidence"]
        cache = {}
        remaining = MAX_REQUEST
        results = []
        for index, item in enumerate(evidence):
            kind, source_id, quote = (
                item["source_type"],
                item["source_id"],
                item["quote"],
            )
            claimed = item.get("source_role")
            result = dict(
                index=index,
                source_type=kind,
                source_id=source_id,
                status="unresolved",
                quote_match=None,
                claimed_role=claimed,
                recorded_role=None,
                role_verified=False,
                excerpt=None,
                matched_span=None,
                source_hash=None,
                source_revision=None,
                locator=dict(message_index=None, page_number=None, chunk_index=None),
                note="Source could not be inspected.",
            )
            results.append(result)
            if kind not in ("memory", "conversation", "file_chunk"):
                result.update(
                    status="unsupported", note="Source type is not supported."
                )
                continue
            key = (kind, source_id)
            if key not in cache and remaining <= 0:
                result["note"] = "Request inspection byte budget is exhausted."
                continue
            if key not in cache:
                cache[key] = _load(session, kind, source_id, remaining)
                if cache[key] is not None and cache[key][1] is not None:
                    remaining -= cache[key][0]
            source = cache[key]
            if source is None:
                result.update(status="not_found", note="Source is absent or deleted.")
                continue
            byte_length, text, locator, revision = source
            result["locator"] = locator.copy()
            if (
                text is None
                or byte_length is None
                or byte_length != len(text.encode("utf-8"))
            ):
                result["note"] = (
                    "Source exceeds the byte inspection budget or is incomplete."
                )
                continue
            result["source_revision"] = revision
            if kind == "conversation":
                try:
                    messages = json.loads(text)
                except (ValueError, TypeError):
                    continue
                if not isinstance(messages, list) or any(
                    not isinstance(m, dict)
                    or not isinstance(m.get("content"), str)
                    or not isinstance(m.get("role"), str)
                    for m in messages
                ):
                    continue
                try:
                    for message in messages:
                        message["content"].encode("utf-8")
                        message["role"].encode("utf-8")
                except UnicodeEncodeError:
                    result["note"] = "Source contains invalid Unicode."
                    continue
                matches = [
                    (i, m) for i, m in enumerate(messages) if quote in m["content"]
                ]
                if not matches:
                    result.update(
                        status="quote_mismatch",
                        quote_match=False,
                        note="Quote was not found in the current messages.",
                    )
                    continue
                i, message = next(
                    (
                        (i, m)
                        for i, m in matches
                        if claimed is not None and m["role"] == claimed
                    ),
                    matches[0],
                )
                text = message["content"]
                result["locator"]["message_index"] = i
                result["recorded_role"] = message["role"]
                result["role_verified"] = (
                    claimed is not None and claimed == message["role"]
                )
            pos = text.find(quote)
            result["source_hash"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if pos < 0:
                result.update(
                    status="quote_mismatch",
                    quote_match=False,
                    note="Quote was not found in the current source.",
                )
                continue
            result.update(
                quote_match=True,
                matched_span={"start": pos, "end": pos + len(quote)},
                excerpt=text[max(0, pos - 200) : max(0, pos - 200) + 1200],
            )
            if (
                kind == "conversation"
                and claimed is not None
                and not result["role_verified"]
            ):
                result.update(
                    status="role_mismatch",
                    note="Quote occurs in a message with a different recorded role.",
                )
            else:
                result.update(
                    status="matched",
                    note="Exact text match in the current local source; this does not establish truth or identity.",
                )
        current = session.exec(
            select(MemoryProposal.revision).where(MemoryProposal.id == proposal_id)
        ).first()
        if current != expected_revision:
            trust.fail(409, "Stale proposal revision")
        return {
            "proposal_id": proposal.id,
            "proposal_revision": proposal.revision,
            "inspected_at": datetime.now(timezone.utc).isoformat(),
            "evidence": results,
        }
