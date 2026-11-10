import json
import uuid
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select
from gigamind.db.database import engine
from gigamind.db.trust_models import MemoryProposal, AcceptedKnowledge, KnowledgeRevision, ActivityEvent


def uid(): return str(uuid.uuid4())
def now(): return datetime.now(timezone.utc).isoformat()
def fail(code, message): raise HTTPException(code, message)
def scope(actor, name):
    if not actor.is_admin and name not in actor.scopes: fail(403, 'Insufficient scope')
def admin(actor):
    if not actor.is_admin: fail(403, 'Administrator required')
def access(actor, project):
    if not actor.is_admin and (project is None or (actor.project_ids is not None and project not in actor.project_ids)): fail(403, 'Project access denied')
def visible(actor, rows, project):
    if project is not None: access(actor, project)
    return [x for x in rows if (project is None or x.project_id == project) and (actor.is_admin or (x.project_id is not None and (actor.project_ids is None or x.project_id in actor.project_ids)))]
def event(s, actor, project, action, target):
    t = now(); s.add(ActivityEvent(id=uid(), project_id=project, writer_id=actor.id, action=action, target_id=target, created_at=t, updated_at=t))
def proposal_dict(p):
    d = p.model_dump() if hasattr(p, 'model_dump') else p.dict(); d.update(json.loads(d.pop('payload_json'))); return d
def memory_dict(m):
    d = m.model_dump() if hasattr(m, 'model_dump') else m.dict(); d.update(json.loads(d.pop('data_json'))); return d
def snapshot(s, m, actor):
    t = now(); s.add(KnowledgeRevision(id=uid(), memory_id=m.id, project_id=m.project_id, revision=m.revision, status=m.status, snapshot_json=json.dumps(memory_dict(m)), writer_id=actor.id, created_at=t, updated_at=t))
def conflicts(s, p, content):
    if not p.get('subject'): return []
    rows = s.exec(select(AcceptedKnowledge).where(AcceptedKnowledge.subject == p['subject'], AcceptedKnowledge.status == 'accepted')).all()
    return [x for x in rows if x.project_id == p['project_id'] and x.content != content]

def create_proposal(actor, *, content, category='general', tags=None, project_id=None, evidence, kind='fact', subject=None, idempotency_key):
    scope(actor, 'memory:propose'); access(actor, project_id)
    if not content or not content.strip() or not idempotency_key or kind not in ('fact', 'preference', 'decision'): fail(422, 'Invalid proposal')
    if not isinstance(evidence, list) or (not actor.is_admin and (not evidence or any(not isinstance(e, dict) or not str(e.get('source_id', '')).strip() or not str(e.get('quote', '')).strip() for e in evidence))): fail(422, 'Evidence requires source_id and quote')
    payload = dict(content=content, category=category, tags=tags or [], project_id=project_id, evidence=evidence, kind=kind, subject=subject)
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    def existing(s):
        p = s.exec(select(MemoryProposal).where(MemoryProposal.writer_id == actor.id, MemoryProposal.idempotency_key == idempotency_key)).first()
        if p and p.payload_json != encoded: fail(409, 'Idempotency key reused with different payload')
        return p
    with Session(engine) as s:
        p = existing(s)
        if p: return {'proposal': proposal_dict(p)}
        t = now(); p = MemoryProposal(id=uid(), writer_id=actor.id, idempotency_key=idempotency_key, payload_json=encoded, project_id=project_id, created_at=t, updated_at=t)
        s.add(p); event(s, actor, project_id, 'proposed', p.id)
        try: s.commit()
        except IntegrityError:
            s.rollback(); p = existing(s)
            if not p: raise
        s.refresh(p)
        return {'proposal': proposal_dict(p)}

def list_proposals(actor, project_id=None):
    scope(actor, 'memory:read')
    with Session(engine) as s:
        rows = visible(actor, s.exec(select(MemoryProposal)).all(), project_id)
        result = []
        for p in rows:
            d = proposal_dict(p); d['conflicts'] = [x.id for x in conflicts(s, d, d['content'])]; result.append(d)
        return {'proposals': result, 'total': len(result)}

def resolve_proposal(actor, proposal_id, *, action, expected_revision, content=None, supersedes=None):
    admin(actor)
    if action not in ('approve', 'reject'): fail(422, 'Invalid action')
    with Session(engine) as s:
        p = s.get(MemoryProposal, proposal_id)
        if not p: fail(404, 'Proposal not found')
        access(actor, p.project_id); data = proposal_dict(p)
        if p.status != 'proposed' or p.revision != expected_revision: fail(409, 'Stale proposal revision')
        value = content if content is not None else data['content']
        if not value.strip(): fail(422, 'Content required')
        found = conflicts(s, data, value) if action == 'approve' else []
        if set(supersedes or []) != {x.id for x in found}: fail(409, 'Explicit supersedes must match conflicts')
        t = now()
        result = s.exec(update(MemoryProposal).where(MemoryProposal.id == proposal_id, MemoryProposal.status == 'proposed', MemoryProposal.revision == expected_revision).values(status='accepted' if action == 'approve' else 'rejected', revision=expected_revision+1, updated_at=t))
        if result.rowcount != 1: fail(409, 'Stale proposal revision')
        for old in found:
            old.status = 'superseded'; old.revision += 1; old.updated_at = t; s.add(old); snapshot(s, old, actor)
        memory = None
        if action == 'approve':
            details = {k: data[k] for k in ('category', 'tags', 'evidence', 'kind')}
            memory = AcceptedKnowledge(id=uid(), proposal_id=p.id, project_id=p.project_id, subject=data['subject'], content=value, data_json=json.dumps(details), writer_id=actor.id, created_at=t, updated_at=t)
            s.add(memory); snapshot(s, memory, actor)
        event(s, actor, p.project_id, action, p.id); s.commit(); s.refresh(p)
        out = {'proposal': proposal_dict(p)}
        if memory:
            s.refresh(memory); out['memory'] = memory_dict(memory)
        return out

def get_memory(actor, memory_id):
    scope(actor, 'memory:read')
    with Session(engine) as s:
        m = s.get(AcceptedKnowledge, memory_id)
        if not m: fail(404, 'Memory not found')
        access(actor, m.project_id); return {'memory': memory_dict(m)}

def get_history(actor, memory_id):
    scope(actor, 'memory:read')
    with Session(engine) as s:
        m = s.get(AcceptedKnowledge, memory_id)
        if not m: fail(404, 'Memory not found')
        access(actor, m.project_id)
        rows = s.exec(select(KnowledgeRevision).where(KnowledgeRevision.memory_id == memory_id).order_by(KnowledgeRevision.revision)).all()
        return {'revisions': [dict(id=r.id, memory_id=r.memory_id, revision=r.revision, status=r.status, writer_id=r.writer_id, created_at=r.created_at, updated_at=r.updated_at, snapshot=json.loads(r.snapshot_json)) for r in rows]}

def restore_memory(actor, memory_id, *, revision, expected_revision):
    admin(actor)
    with Session(engine) as s:
        m = s.get(AcceptedKnowledge, memory_id)
        if not m: fail(404, 'Memory not found')
        access(actor, m.project_id)
        old = s.exec(select(KnowledgeRevision).where(KnowledgeRevision.memory_id == memory_id, KnowledgeRevision.revision == revision)).first()
        if not old: fail(404, 'Revision not found')
        data = json.loads(old.snapshot_json); t = now()
        # Restoring an accepted fact must not silently recreate a conflict.
        if data['status'] == 'accepted' and conflicts(s, data, data['content']): fail(409, 'Restoration conflicts with accepted knowledge')
        res = s.exec(update(AcceptedKnowledge).where(AcceptedKnowledge.id == memory_id, AcceptedKnowledge.revision == expected_revision).values(content=data['content'], status=data['status'], data_json=json.dumps({k: data[k] for k in ('category','tags','evidence','kind')}), revision=expected_revision+1, updated_at=t, writer_id=actor.id))
        if res.rowcount != 1: fail(409, 'Stale memory revision')
        s.refresh(m); snapshot(s, m, actor); event(s, actor, m.project_id, 'restore', m.id); s.commit(); s.refresh(m); return {'memory': memory_dict(m)}

def list_activity(actor, project_id=None):
    scope(actor, 'memory:read')
    with Session(engine) as s:
        rows = visible(actor, s.exec(select(ActivityEvent)).all(), project_id)
        return {'events': [x.model_dump() if hasattr(x, 'model_dump') else x.dict() for x in rows]}
