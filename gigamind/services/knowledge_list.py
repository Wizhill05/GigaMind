from sqlalchemy import func
from sqlmodel import Session, select

from gigamind.db.trust_models import AcceptedKnowledge
from gigamind.services import context, trust, knowledge_validity


def list_knowledge(
    actor, q=None, project_id=None, status="accepted", limit=20, offset=0
):
    trust.scope(actor, "memory:read")
    trust.pagination(limit, offset)
    if type(limit) is not int or type(offset) is not int or offset > 100000:
        trust.fail(422, "Invalid pagination")
    if project_id is not None and (
        not isinstance(project_id, str)
        or not project_id.strip()
        or len(project_id) > 255
    ):
        trust.fail(422, "Invalid project ID")
    if not actor.is_admin and project_id is None:
        trust.fail(403, "Project required")
    if not actor.is_admin and status != "accepted":
        trust.fail(403, "Administrator required")
    if status not in {"accepted", "superseded", "deleted", "expired"}:
        trust.fail(422, "Invalid status")
    if q is not None and (not isinstance(q, str) or len(q) > 1000):
        trust.fail(422, "Query too long")
    as_of = knowledge_validity.current_time()
    query = context._knowledge_query(actor, project_id).where(
        AcceptedKnowledge.status == status
    )
    if not actor.is_admin:
        query = query.where(knowledge_validity.active_clause(as_of))
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(
            AcceptedKnowledge.content.ilike(f"%{escaped}%", escape="\\")
        )
    with Session(trust.engine) as session:
        total = session.exec(select(func.count()).select_from(query.subquery())).one()
        rows = session.exec(
            query.order_by(
                AcceptedKnowledge.updated_at.desc(), AcceptedKnowledge.id.desc()
            )
            .offset(offset)
            .limit(limit)
        ).all()
        memories = []
        for row in rows:
            item = trust.memory_dict(row)
            if row.status != "accepted":
                item["validity_status"] = "inactive"
            elif row.valid_from is not None and row.valid_from > as_of:
                item["validity_status"] = "future"
            elif row.valid_until is not None and row.valid_until <= as_of:
                item["validity_status"] = "expired"
            else:
                item["validity_status"] = "active"
            memories.append(item)
        return {"memories": memories, "total": total, "as_of": as_of}
