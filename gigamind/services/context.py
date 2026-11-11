"""Project-scoped lexical retrieval of approved knowledge."""

import json
import re

from fastapi import HTTPException
from sqlalchemy import or_, case, text
from sqlmodel import Session

from gigamind.db.trust_models import AcceptedKnowledge
from gigamind.services import trust, knowledge_validity


def _knowledge_query(actor, project_id):
    query = trust.scoped_query(actor, AcceptedKnowledge, project_id)
    if actor.is_admin and project_id is None:
        query = query.where(AcceptedKnowledge.project_id.is_(None))
    return query


def search_accepted(actor, query, project_id=None, limit=5):
    trust.scope(actor, "memory:read")
    if not actor.is_admin and project_id is None:
        trust.fail(403, "Project required")
    if project_id is not None:
        trust.access(actor, project_id)
    trust.pagination(limit, 0)
    if not isinstance(query, str) or not query.strip() or len(query) > 1000:
        trust.fail(422, "Query required")
    stop_words = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "do",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "my",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "was",
        "we",
        "what",
        "which",
        "with",
        "you",
    }
    words = list(
        dict.fromkeys(
            word
            for word in re.findall(r"[^\W_]+", query.casefold(), flags=re.UNICODE)
            if word not in stop_words
        )
    )[:20]
    if not words:
        return []
    clauses = [
        AcceptedKnowledge.content.ilike("%" + w + "%", escape="\\") for w in words
    ]
    score = sum(case((clause, 1), else_=0) for clause in clauses)
    with Session(trust.engine) as session:
        stmt = (
            _knowledge_query(actor, project_id)
            .where(
                AcceptedKnowledge.status == "accepted",
                knowledge_validity.active_clause(),
                or_(*clauses),
            )
            .order_by(
                score.desc(), AcceptedKnowledge.updated_at.desc(), AcceptedKnowledge.id
            )
            .limit(limit)
        )
        return [
            dict(trust.memory_dict(m), source="accepted_knowledge")
            for m in session.exec(stmt).all()
        ]


def get_memory(actor, memory_id):
    result = trust.get_memory(actor, memory_id)
    memory = result["memory"]
    if memory["status"] == "deleted" or not knowledge_validity.active(
        memory["valid_from"], memory["valid_until"]
    ):
        raise HTTPException(404, "Memory not found")
    result["memory"]["source"] = "accepted_knowledge"
    return result


def get_context(actor, query, project_id=None, token_budget=4096):
    # UTF-8 JSON byte count is a conservative upper bound for byte-based tokenizers.
    if not isinstance(token_budget, int) or not 64 <= token_budget <= 100000:
        raise HTTPException(422, "token_budget must be between 64 and 100000")
    rows = search_accepted(actor, query, project_id, 100)
    preference_filter = (
        "CAST(data_json AS JSONB)->>'kind' = 'preference'"
        if trust.engine.dialect.name == "postgresql"
        else "json_extract(data_json, '$.kind') = 'preference'"
    )
    with Session(trust.engine) as session:
        rules = session.exec(
            _knowledge_query(actor, project_id)
            .where(
                AcceptedKnowledge.status == "accepted",
                knowledge_validity.active_clause(),
                text(preference_filter),
            )
            .order_by(AcceptedKnowledge.updated_at.desc(), AcceptedKnowledge.id)
            .limit(100)
        ).all()
        rule_rows = [
            dict(trust.memory_dict(rule), source="accepted_knowledge") for rule in rules
        ]
    rule_ids = {row["id"] for row in rule_rows}
    rows = rule_rows + [row for row in rows if row["id"] not in rule_ids]
    result = {"rules": [], "memories": [], "citations": [], "handoff": None}
    for row in rows:
        citations = [dict(e, memory_id=row["id"]) for e in row.get("evidence", [])]
        target = "rules" if row.get("kind") == "preference" else "memories"
        candidate = dict(
            result,
            **{target: result[target] + [row]},
            citations=result["citations"] + citations,
        )
        if (
            len(json.dumps(candidate, ensure_ascii=True).encode("utf-8"))
            <= token_budget
        ):
            result = candidate
    from gigamind.services import coordination

    handoff = coordination.latest_handoff(actor, project_id)["handoff"]
    candidate = dict(result, handoff=handoff)
    if (
        handoff
        and len(json.dumps(candidate, ensure_ascii=True).encode("utf-8"))
        <= token_budget
    ):
        result = candidate
    return result
