"""Project-scoped lexical retrieval of approved knowledge."""
import json
import re

from fastapi import HTTPException
from sqlalchemy import or_
from sqlmodel import Session

from gigamind.db.trust_models import AcceptedKnowledge
from gigamind.services import trust


def search_accepted(actor, query, project_id=None, limit=5):
    trust.scope(actor, 'memory:read')
    if not actor.is_admin and project_id is None:
        trust.fail(403, 'Project required')
    trust.pagination(limit, 0)
    if not isinstance(query, str) or not query.strip() or len(query) > 1000:
        trust.fail(422, 'Query required')
    words = re.findall(r'[^\W_]+', query.casefold(), flags=re.UNICODE)[:20]
    if not words:
        return []
    clauses = [AcceptedKnowledge.content.ilike('%' + w + '%', escape='\\') for w in words]
    with Session(trust.engine) as session:
        stmt = trust.scoped_query(actor, AcceptedKnowledge, project_id).where(
            AcceptedKnowledge.status == 'accepted', or_(*clauses)
        ).order_by(AcceptedKnowledge.updated_at.desc(), AcceptedKnowledge.id).limit(limit)
        return [dict(trust.memory_dict(m), source='accepted_knowledge') for m in session.exec(stmt).all()]


def get_memory(actor, memory_id):
    result = trust.get_memory(actor, memory_id)
    result['memory']['source'] = 'accepted_knowledge'
    return result


def get_context(actor, query, project_id=None, token_budget=4096):
    # UTF-8 JSON byte count is a conservative upper bound for byte-based tokenizers.
    if not isinstance(token_budget, int) or not 64 <= token_budget <= 100000:
        raise HTTPException(422, 'token_budget must be between 64 and 100000')
    rows = search_accepted(actor, query, project_id, 100)
    result = {'rules': [], 'memories': [], 'citations': [], 'handoff': None}
    for row in rows:
        citations = [dict(e, memory_id=row['id']) for e in row.get('evidence', [])]
        candidate = dict(result, memories=result['memories'] + [row], citations=result['citations'] + citations)
        if len(json.dumps(candidate, ensure_ascii=True).encode('utf-8')) <= token_budget:
            result = candidate
    return result
