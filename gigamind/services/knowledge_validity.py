"""Validity windows for accepted knowledge."""

from datetime import datetime, timezone

from sqlalchemy import and_, or_, update
from sqlmodel import Session

from gigamind.db.trust_models import AcceptedKnowledge
from gigamind.services import trust


def normalize(value):
    if value is None:
        return None
    if not isinstance(value, str):
        trust.fail(422, "Timestamp must be a timezone-aware ISO string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")
    except (ValueError, OverflowError):
        trust.fail(422, "Timestamp must be a timezone-aware ISO string")


def current_time():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def active_clause(now=None):
    now = normalize(now) if now is not None else current_time()
    return and_(
        or_(
            AcceptedKnowledge.valid_from.is_(None), AcceptedKnowledge.valid_from <= now
        ),
        or_(
            AcceptedKnowledge.valid_until.is_(None), AcceptedKnowledge.valid_until > now
        ),
    )


def active(valid_from, valid_until, now=None):
    now = normalize(now) if now is not None else current_time()
    return (valid_from is None or valid_from <= now) and (
        valid_until is None or now < valid_until
    )


@trust.concurrent_guard
def set_validity(actor, memory_id, *, expected_revision, valid_from, valid_until):
    trust.admin(actor)
    if type(expected_revision) is not int or expected_revision < 1:
        trust.fail(422, "Invalid expected revision")
    start, end = normalize(valid_from), normalize(valid_until)
    if start is not None and end is not None and start >= end:
        trust.fail(422, "valid_from must be before valid_until")
    with Session(trust.engine, expire_on_commit=False) as session:
        memory = session.get(AcceptedKnowledge, memory_id)
        if memory is None:
            trust.fail(404, "Memory not found")
        trust.access(actor, memory.project_id)
        result = session.exec(
            update(AcceptedKnowledge)
            .where(
                AcceptedKnowledge.id == memory_id,
                AcceptedKnowledge.status == "accepted",
                AcceptedKnowledge.revision == expected_revision,
            )
            .values(
                valid_from=start,
                valid_until=end,
                revision=expected_revision + 1,
                updated_at=trust.now(),
                writer_id=actor.id,
            )
        )
        if result.rowcount != 1:
            trust.fail(409, "Stale memory revision or memory is not accepted")
        session.refresh(memory)
        trust.snapshot(session, memory, actor)
        trust.event(
            session,
            actor,
            memory.project_id,
            "validity",
            memory.id,
            revision=memory.revision,
        )
        session.commit()
        return {"memory": trust.memory_dict(memory)}
