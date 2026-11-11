import json
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select
from gigamind.db.coordination import Handoff, MemoryIssue
from gigamind.db.trust_models import AcceptedKnowledge
from gigamind.services import trust
from gigamind.services.coordination_schema import (
    HandoffInput,
    IssueInput,
    IssueResolution,
)


def serialize(row):
    result = row.model_dump()
    result.update(json.loads(result.pop("payload_json")))
    result.pop("idempotency_key", None)
    if isinstance(row, Handoff):
        result["record_type"] = "agent_report"
    return result


def _save(actor, model, values, label):
    key = values.pop("idempotency_key")
    project = values["project_id"]
    trust.access(actor, project)
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"))

    def existing(session):
        row = session.exec(
            select(model).where(
                model.writer_id == actor.id, model.idempotency_key == key
            )
        ).first()
        if row and row.payload_json != payload:
            trust.fail(409, "Idempotency key reused with different payload")
        return row

    with Session(trust.engine) as session:
        row = existing(session)
        if row:
            return {label: serialize(row)}
        if model is MemoryIssue:
            memory = session.get(AcceptedKnowledge, values["memory_id"])
            if (
                not memory
                or memory.status != "accepted"
                or memory.project_id != project
            ):
                trust.fail(404, "Accepted memory not found in scope")
        now = trust.now()
        extra = (
            {"status": values["status"]}
            if model is Handoff
            else {"memory_id": values["memory_id"]}
        )
        row = model(
            id=trust.uid(),
            writer_id=actor.id,
            idempotency_key=key,
            project_id=project,
            payload_json=payload,
            created_at=now,
            updated_at=now,
            **extra,
        )
        session.add(row)
        trust.event(
            session,
            actor,
            project,
            "handoff_saved" if model is Handoff else "memory_issue_reported",
            row.id,
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            row = existing(session)
            if not row:
                raise
        session.refresh(row)
        return {label: serialize(row)}


@trust.concurrent_guard
def save_handoff(actor, **kwargs):
    trust.scope(actor, "memory:propose")
    return _save(actor, Handoff, trust.validate(HandoffInput, **kwargs), "handoff")


@trust.concurrent_guard
def report_memory_issue(actor, **kwargs):
    trust.scope(actor, "memory:read")
    trust.scope(actor, "memory:propose")
    return _save(actor, MemoryIssue, trust.validate(IssueInput, **kwargs), "issue")


def _list(actor, model, project_id, limit, offset):
    trust.scope(actor, "memory:read")
    trust.access(actor, project_id)
    trust.pagination(limit, offset)
    with Session(trust.engine) as session:
        query = select(model).where(model.project_id == project_id)
        if model is MemoryIssue and not actor.is_admin:
            query = query.where(model.writer_id == actor.id)
        total = session.exec(select(func.count()).select_from(query.subquery())).one()
        rows = session.exec(
            query.order_by(model.created_at.desc(), model.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return [serialize(row) for row in rows], total


def list_handoffs(actor, project_id=None, limit=20, offset=0):
    rows, total = _list(actor, Handoff, project_id, limit, offset)
    return {"handoffs": rows, "total": total}


def latest_handoff(actor, project_id=None):
    rows, _ = _list(actor, Handoff, project_id, 1, 0)
    return {"handoff": rows[0] if rows else None}


def list_issues(actor, project_id=None, limit=20, offset=0):
    rows, total = _list(actor, MemoryIssue, project_id, limit, offset)
    return {"issues": rows, "total": total}


@trust.concurrent_guard
def resolve_issue(actor, issue_id, **kwargs):
    trust.admin(actor)
    values = trust.validate(IssueResolution, **kwargs)
    with Session(trust.engine) as session:
        row = session.get(MemoryIssue, issue_id)
        if not row:
            trust.fail(404, "Issue not found")
        changed = session.exec(
            update(MemoryIssue)
            .where(
                MemoryIssue.id == issue_id,
                MemoryIssue.revision == values["expected_revision"],
                MemoryIssue.status == "open",
            )
            .values(
                status=values["status"],
                revision=values["expected_revision"] + 1,
                updated_at=trust.now(),
            )
        )
        if changed.rowcount != 1:
            trust.fail(409, "Stale issue revision")
        session.refresh(row)
        trust.event(
            session,
            actor,
            row.project_id,
            "memory_issue_" + values["status"],
            row.id,
            row.revision,
        )
        session.commit()
        session.refresh(row)
        return {"issue": serialize(row)}
