import json
import uuid
from functools import wraps
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import update, func
from sqlalchemy.exc import IntegrityError, OperationalError
from pydantic import ValidationError
from gigamind.services.trust_schema import (
    Proposal,
    Resolution,
    Restore,
    ApprovalPreview,
)
from sqlmodel import Session, select
from gigamind.db.database import engine
from gigamind.db.trust_models import (
    MemoryProposal,
    AcceptedKnowledge,
    KnowledgeRevision,
    ActivityEvent,
)


def uid():
    return str(uuid.uuid4())


def now():
    return datetime.now(timezone.utc).isoformat()


def fail(code, message):
    raise HTTPException(code, message)


def scope(actor, name):
    if not actor.is_admin and name not in actor.scopes:
        fail(403, "Insufficient scope")


def admin(actor):
    if not actor.is_admin:
        fail(403, "Administrator required")


def access(actor, project):
    if not actor.is_admin and (
        project is None
        or (actor.project_ids is not None and project not in actor.project_ids)
    ):
        fail(403, "Project access denied")


def scoped_query(actor, model, project):
    query = select(model)
    if project is not None:
        access(actor, project)
        return query.where(model.project_id == project)
    if not actor.is_admin:
        query = query.where(model.project_id.is_not(None))
        if actor.project_ids is not None:
            query = query.where(model.project_id.in_(actor.project_ids))
    return query


def pagination(limit, offset):
    if (
        not isinstance(limit, int)
        or not 1 <= limit <= 100
        or not isinstance(offset, int)
        or offset < 0
    ):
        fail(422, "Invalid pagination")


def validate(model, **values):
    try:
        return model(**values).model_dump()
    except ValidationError as exc:
        raise HTTPException(422, detail=exc.errors(include_context=False)) from exc


def event(s, actor, project, action, target, revision=1):
    t = now()
    s.add(
        ActivityEvent(
            id=uid(),
            project_id=project,
            writer_id=actor.id,
            action=action,
            target_id=target,
            revision=revision,
            created_at=t,
            updated_at=t,
        )
    )


def proposal_dict(p):
    d = p.model_dump() if hasattr(p, "model_dump") else p.dict()
    d.update(json.loads(d.pop("payload_json")))
    return d


def memory_dict(m):
    d = m.model_dump() if hasattr(m, "model_dump") else m.dict()
    d.update(json.loads(d.pop("data_json")))
    return d


def snapshot(s, m, actor):
    t = now()
    s.add(
        KnowledgeRevision(
            id=uid(),
            memory_id=m.id,
            project_id=m.project_id,
            revision=m.revision,
            status=m.status,
            snapshot_json=json.dumps(memory_dict(m)),
            writer_id=actor.id,
            created_at=t,
            updated_at=t,
        )
    )


def conflicts(s, p, content, exclude_id=None):
    if not p.get("subject"):
        return []
    query = select(AcceptedKnowledge).where(
        AcceptedKnowledge.subject == p["subject"],
        AcceptedKnowledge.project_id == p["project_id"],
        AcceptedKnowledge.status == "accepted",
        AcceptedKnowledge.content != content,
    )
    if exclude_id:
        query = query.where(AcceptedKnowledge.id != exclude_id)
    return list(s.exec(query).all())


def concurrent_guard(fn):
    @wraps(fn)
    def guarded(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except IntegrityError as exc:
            raise HTTPException(409, "Concurrent update; retry") from exc
        except OperationalError as exc:
            if (
                "locked" not in str(exc).lower()
                and "deadlock" not in str(exc).lower()
                and "serialization" not in str(exc).lower()
            ):
                raise
            raise HTTPException(409, "Concurrent update; retry") from exc

    return guarded


@concurrent_guard
def create_proposal(
    actor,
    *,
    content,
    category="general",
    tags=None,
    project_id=None,
    evidence,
    kind="fact",
    subject=None,
    idempotency_key,
):
    scope(actor, "memory:propose")
    values = validate(
        Proposal,
        content=content,
        category=category,
        tags=tags if tags is not None else [],
        project_id=project_id,
        evidence=evidence,
        kind=kind,
        subject=subject,
        idempotency_key=idempotency_key,
    )
    idempotency_key = values.pop("idempotency_key")
    project_id = values["project_id"]
    access(actor, project_id)
    if not actor.is_admin and not values["evidence"]:
        fail(422, "Evidence required")
    payload = values
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def existing(s):
        p = s.exec(
            select(MemoryProposal).where(
                MemoryProposal.writer_id == actor.id,
                MemoryProposal.idempotency_key == idempotency_key,
            )
        ).first()
        if p:
            previous = json.loads(p.payload_json)
            previous.pop("accepted_memory_id", None)
            if previous != payload:
                fail(409, "Idempotency key reused with different payload")
        return p

    with Session(engine) as s:
        p = existing(s)
        if p:
            return {"proposal": proposal_dict(p)}
        t = now()
        p = MemoryProposal(
            id=uid(),
            writer_id=actor.id,
            idempotency_key=idempotency_key,
            payload_json=encoded,
            project_id=project_id,
            created_at=t,
            updated_at=t,
        )
        s.add(p)
        event(s, actor, project_id, "proposed", p.id)
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            p = existing(s)
            if not p:
                raise
        s.refresh(p)
        return {"proposal": proposal_dict(p)}


def list_proposals(actor, project_id=None, *, limit=100, offset=0):
    scope(actor, "memory:read")
    pagination(limit, offset)
    with Session(engine) as s:
        query = scoped_query(actor, MemoryProposal, project_id)
        total = s.exec(select(func.count()).select_from(query.subquery())).one()
        rows = s.exec(
            query.order_by(MemoryProposal.created_at, MemoryProposal.id)
            .offset(offset)
            .limit(limit)
        ).all()
        result = []
        for p in rows:
            d = proposal_dict(p)
            d["conflicts"] = [x.id for x in conflicts(s, d, d["content"])]
            result.append(d)
        return {"proposals": result, "total": total}


def preview_proposal(actor, proposal_id, *, content, expected_revision):
    admin(actor)
    values = validate(
        ApprovalPreview, content=content, expected_revision=expected_revision
    )
    with Session(engine) as session:
        proposal = session.get(MemoryProposal, proposal_id)
        if proposal is None:
            fail(404, "Proposal not found")
        access(actor, proposal.project_id)
        if (
            proposal.status != "proposed"
            or proposal.revision != values["expected_revision"]
        ):
            fail(409, "Stale proposal revision")
        records = conflicts(session, proposal_dict(proposal), values["content"])
        return {
            "proposal_id": proposal.id,
            "revision": proposal.revision,
            "content": values["content"],
            "conflicts": [memory_dict(record) for record in records],
        }


@concurrent_guard
def resolve_proposal(
    actor, proposal_id, *, action, expected_revision, content=None, supersedes=None
):
    admin(actor)
    validated = validate(
        Resolution,
        action=action,
        expected_revision=expected_revision,
        content=content,
        supersedes=supersedes or [],
    )
    action = validated["action"]
    expected_revision = validated["expected_revision"]
    content = validated["content"]
    supersedes = validated["supersedes"]
    with Session(engine) as s:
        p = s.get(MemoryProposal, proposal_id)
        if not p:
            fail(404, "Proposal not found")
        access(actor, p.project_id)
        data = proposal_dict(p)
        if p.status != "proposed" or p.revision != expected_revision:
            fail(409, "Stale proposal revision")
        value = content if content is not None else data["content"]
        if not value.strip():
            fail(422, "Content required")
        found = conflicts(s, data, value) if action == "approve" else []
        if set(supersedes or []) != {x.id for x in found}:
            fail(409, "Explicit supersedes must match conflicts")
        t = now()
        result = s.exec(
            update(MemoryProposal)
            .where(
                MemoryProposal.id == proposal_id,
                MemoryProposal.status == "proposed",
                MemoryProposal.revision == expected_revision,
            )
            .values(
                status="accepted" if action == "approve" else "rejected",
                revision=expected_revision + 1,
                updated_at=t,
            )
        )
        if result.rowcount != 1:
            fail(409, "Stale proposal revision")
        for old in found:
            previous_revision = old.revision
            changed = s.exec(
                update(AcceptedKnowledge)
                .where(
                    AcceptedKnowledge.id == old.id,
                    AcceptedKnowledge.status == "accepted",
                    AcceptedKnowledge.revision == previous_revision,
                )
                .values(
                    status="superseded", revision=previous_revision + 1, updated_at=t
                )
            )
            if changed.rowcount != 1:
                fail(409, "Conflicting knowledge changed; reload proposal")
            s.refresh(old)
            snapshot(s, old, actor)
        s.flush()
        memory = None
        if action == "approve":
            details = {k: data[k] for k in ("category", "tags", "evidence", "kind")}
            memory = None
            if data["subject"]:
                memory = s.exec(
                    select(AcceptedKnowledge).where(
                        AcceptedKnowledge.project_id == p.project_id,
                        AcceptedKnowledge.subject == data["subject"],
                        AcceptedKnowledge.status == "accepted",
                        AcceptedKnowledge.content == value,
                    )
                ).first()
            if memory is None:
                memory = AcceptedKnowledge(
                    id=uid(),
                    proposal_id=p.id,
                    project_id=p.project_id,
                    subject=data["subject"],
                    content=value,
                    data_json=json.dumps(details),
                    writer_id=actor.id,
                    created_at=t,
                    updated_at=t,
                )
                s.add(memory)
                snapshot(s, memory, actor)
            data["accepted_memory_id"] = memory.id
            p.payload_json = json.dumps(
                {
                    k: v
                    for k, v in data.items()
                    if k
                    in (
                        "content",
                        "category",
                        "tags",
                        "project_id",
                        "evidence",
                        "kind",
                        "subject",
                        "accepted_memory_id",
                    )
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            s.add(p)
        event(s, actor, p.project_id, action, p.id)
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            fail(409, "Concurrent knowledge update; retry")
        s.refresh(p)
        out = {"proposal": proposal_dict(p)}
        if memory:
            s.refresh(memory)
            out["memory"] = memory_dict(memory)
        return out


def get_memory(actor, memory_id):
    scope(actor, "memory:read")
    with Session(engine) as s:
        m = s.get(AcceptedKnowledge, memory_id)
        if not m:
            fail(404, "Memory not found")
        access(actor, m.project_id)
        from gigamind.services import knowledge_validity

        if not actor.is_admin and (
            m.status == "deleted"
            or not knowledge_validity.active(m.valid_from, m.valid_until)
        ):
            fail(404, "Memory not found")
        return {"memory": memory_dict(m)}


def get_history(actor, memory_id):
    scope(actor, "memory:read")
    with Session(engine) as s:
        m = s.get(AcceptedKnowledge, memory_id)
        if not m:
            fail(404, "Memory not found")
        access(actor, m.project_id)
        from gigamind.services import knowledge_validity

        if not actor.is_admin and (
            m.status == "deleted"
            or not knowledge_validity.active(m.valid_from, m.valid_until)
        ):
            fail(404, "Memory not found")
        rows = s.exec(
            select(KnowledgeRevision)
            .where(KnowledgeRevision.memory_id == memory_id)
            .order_by(KnowledgeRevision.revision)
        ).all()
        return {
            "revisions": [
                dict(
                    id=r.id,
                    memory_id=r.memory_id,
                    revision=r.revision,
                    status=r.status,
                    writer_id=r.writer_id,
                    created_at=r.created_at,
                    updated_at=r.updated_at,
                    snapshot=json.loads(r.snapshot_json),
                )
                for r in rows
            ]
        }


@concurrent_guard
def delete_memory(actor, memory_id, *, expected_revision):
    admin(actor)
    if type(expected_revision) is not int or expected_revision < 1:
        fail(422, "Invalid expected revision")
    with Session(engine, expire_on_commit=False) as s:
        m = s.get(AcceptedKnowledge, memory_id)
        if not m:
            fail(404, "Memory not found")
        access(actor, m.project_id)
        result = s.exec(
            update(AcceptedKnowledge)
            .where(
                AcceptedKnowledge.id == memory_id,
                AcceptedKnowledge.status == "accepted",
                AcceptedKnowledge.revision == expected_revision,
            )
            .values(
                status="deleted",
                revision=expected_revision + 1,
                updated_at=now(),
                writer_id=actor.id,
            )
        )
        if result.rowcount != 1:
            fail(409, "Stale memory revision or memory is not accepted")
        s.refresh(m)
        snapshot(s, m, actor)
        event(s, actor, m.project_id, "delete", m.id, revision=m.revision)
        s.commit()
        return {"memory": memory_dict(m)}


@concurrent_guard
def restore_memory(actor, memory_id, *, revision, expected_revision):
    admin(actor)
    validated = validate(
        Restore, revision=revision, expected_revision=expected_revision
    )
    revision = validated["revision"]
    expected_revision = validated["expected_revision"]
    with Session(engine) as s:
        m = s.get(AcceptedKnowledge, memory_id)
        if not m:
            fail(404, "Memory not found")
        access(actor, m.project_id)
        old = s.exec(
            select(KnowledgeRevision).where(
                KnowledgeRevision.memory_id == memory_id,
                KnowledgeRevision.revision == revision,
            )
        ).first()
        if not old:
            fail(404, "Revision not found")
        data = json.loads(old.snapshot_json)
        t = now()
        # Restoring an accepted fact must not silently recreate a conflict.
        if data["status"] == "accepted" and conflicts(
            s, data, data["content"], exclude_id=memory_id
        ):
            fail(409, "Restoration conflicts with accepted knowledge")
        res = s.exec(
            update(AcceptedKnowledge)
            .where(
                AcceptedKnowledge.id == memory_id,
                AcceptedKnowledge.revision == expected_revision,
            )
            .values(
                content=data["content"],
                valid_from=data.get("valid_from", AcceptedKnowledge.valid_from),
                valid_until=data.get("valid_until", AcceptedKnowledge.valid_until),
                status=data["status"],
                data_json=json.dumps(
                    {k: data[k] for k in ("category", "tags", "evidence", "kind")}
                ),
                revision=expected_revision + 1,
                updated_at=t,
                writer_id=actor.id,
            )
        )
        if res.rowcount != 1:
            fail(409, "Stale memory revision")
        s.refresh(m)
        snapshot(s, m, actor)
        event(s, actor, m.project_id, "restore", m.id)
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            fail(409, "Concurrent knowledge update; retry")
        s.refresh(m)
        return {"memory": memory_dict(m)}


def list_activity(actor, project_id=None, *, limit=100, offset=0):
    scope(actor, "memory:read")
    pagination(limit, offset)
    with Session(engine) as s:
        query = scoped_query(actor, ActivityEvent, project_id)
        total = s.exec(select(func.count()).select_from(query.subquery())).one()
        rows = s.exec(
            query.order_by(ActivityEvent.created_at.desc(), ActivityEvent.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return {
            "total": total,
            "events": [
                x.model_dump() if hasattr(x, "model_dump") else x.dict() for x in rows
            ],
        }
