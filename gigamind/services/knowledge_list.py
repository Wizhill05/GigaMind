from sqlalchemy import func
from sqlmodel import Session, select

from gigamind.db.trust_models import AcceptedKnowledge
from gigamind.services import context, trust


def list_knowledge(actor, q=None, project_id=None, status="accepted", limit=20, offset=0):
    trust.scope(actor, "memory:read")
    trust.pagination(limit, offset)
    if not actor.is_admin and project_id is None:
        trust.fail(403, "Project required")
    if not actor.is_admin and status != "accepted":
        trust.fail(403, "Administrator required")
    if status not in {"accepted", "superseded", "deleted", "expired"}:
        trust.fail(422, "Invalid status")
    if q is not None and len(q) > 1000:
        trust.fail(422, "Query too long")
    query = context._knowledge_query(actor, project_id).where(AcceptedKnowledge.status == status)
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(AcceptedKnowledge.content.ilike(f"%{escaped}%", escape="\\"))
    with Session(trust.engine) as session:
        total = session.exec(select(func.count()).select_from(query.subquery())).one()
        rows = session.exec(query.order_by(AcceptedKnowledge.updated_at.desc(), AcceptedKnowledge.id.desc()).offset(offset).limit(limit)).all()
        return {"memories": [trust.memory_dict(row) for row in rows], "total": total}
