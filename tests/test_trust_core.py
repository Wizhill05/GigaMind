import os
os.environ['PYTHON_DOTENV_DISABLED'] = '1'
os.environ['DATABASE_URL'] = ''
os.environ['DB_PATH'] = '/tmp/gigamind-trust-import-unused.db'
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlmodel import create_engine
from gigamind.db.trust_models import initialize_trust_tables
from gigamind.security import Actor, get_actor
from gigamind.services import trust
from gigamind.routers.review import router

@pytest.fixture
def setup(tmp_path, monkeypatch):
    engine = create_engine(f'sqlite:///{tmp_path}/test.db', connect_args={'check_same_thread': False})
    initialize_trust_tables(engine); monkeypatch.setattr(trust, 'engine', engine)
    admin = Actor('human', set(), None, True)
    agent = Actor('agent', {'memory:read', 'memory:propose', 'memory:approve'}, {'a'})
    return admin, agent

def proposal(actor, key='one', content='first', project='a'):
    return trust.create_proposal(actor, content=content, project_id=project, subject='topic', evidence=[{'source_type':'doc', 'source_id':'1', 'quote':'text'}], idempotency_key=key)['proposal']

def error(code, fn, *args, **kwargs):
    with pytest.raises(HTTPException) as exc: fn(*args, **kwargs)
    assert exc.value.status_code == code

def test_lifecycle(setup):
    admin, agent = setup
    p = proposal(agent)
    assert proposal(agent)['id'] == p['id']
    error(409, proposal, agent, content='different')
    error(404, trust.get_memory, agent, p['id'])
    error(403, trust.resolve_proposal, agent, p['id'], action='approve', expected_revision=1)
    out = trust.resolve_proposal(admin, p['id'], action='approve', expected_revision=1)
    m = out['memory']; assert m['content'] == 'first'
    error(409, trust.resolve_proposal, admin, p['id'], action='approve', expected_revision=1)
    assert trust.get_history(agent, m['id'])['revisions'][0]['snapshot']['evidence'][0]['quote'] == 'text'
    second = proposal(agent, 'two', 'second')
    assert trust.list_proposals(agent)['proposals'][1]['conflicts'] == [m['id']]
    error(409, trust.resolve_proposal, admin, second['id'], action='approve', expected_revision=1)
    trust.resolve_proposal(admin, second['id'], action='approve', expected_revision=1, supersedes=[m['id']])
    assert trust.get_memory(agent, m['id'])['memory']['status'] == 'superseded'
    error(409, trust.restore_memory, admin, m['id'], revision=1, expected_revision=2)
    restored = trust.restore_memory(admin, m['id'], revision=2, expected_revision=2)['memory']
    assert restored['revision'] == 3
    error(409, trust.restore_memory, admin, m['id'], revision=2, expected_revision=2)
    assert len(trust.get_history(admin, m['id'])['revisions']) == 3
    rejected = proposal(agent, 'three', 'third')
    assert trust.resolve_proposal(admin, rejected['id'], action='reject', expected_revision=1)['proposal']['status'] == 'rejected'
    assert trust.list_activity(agent)['events']

def test_project_and_router(setup):
    admin, agent = setup
    p = proposal(admin, project='b'); m = trust.resolve_proposal(admin, p['id'], action='approve', expected_revision=1)['memory']
    assert trust.list_proposals(agent)['total'] == 0
    for fn in (trust.get_memory, trust.get_history): error(403, fn, agent, m['id'])
    error(403, trust.list_proposals, agent, 'b')
    error(403, trust.restore_memory, agent, m['id'], revision=1, expected_revision=1)
    error(403, proposal, agent, project=None)
    app = FastAPI(); app.include_router(router)
    app.dependency_overrides[get_actor] = lambda: agent
    client = TestClient(app)
    assert client.get('/api/v1/review/proposals').json()['total'] == 0
    assert client.get(f"/api/v1/review/memories/{m['id']}/history").status_code == 403
    assert client.post(f"/api/v1/review/proposals/{p['id']}/resolve", json={'action':'approve','expected_revision':1}).status_code == 403
    app.dependency_overrides.clear()
    assert client.get('/api/v1/review/activity').status_code == 401

def test_validation_dedup_and_database_constraint(setup):
    from sqlalchemy.exc import IntegrityError
    from sqlmodel import Session
    from gigamind.db.trust_models import AcceptedKnowledge

    admin, agent = setup
    error(422, trust.create_proposal, agent, content='x', project_id='a', evidence=[{'source_type': 'doc', 'source_id': None, 'quote': None}], idempotency_key='bad')
    first = proposal(agent)
    memory = trust.resolve_proposal(admin, first['id'], action='approve', expected_revision=1)['memory']
    second = proposal(agent, 'same')
    result = trust.resolve_proposal(admin, second['id'], action='approve', expected_revision=1)
    assert result['memory']['id'] == memory['id']
    assert result['proposal']['accepted_memory_id'] == memory['id']
    assert proposal(agent)['id'] == first['id']
    with Session(trust.engine) as session:
        session.add(AcceptedKnowledge(id='duplicate', proposal_id='x', project_id='a', subject='topic', content='x', data_json='{}', writer_id='x', created_at='x', updated_at='x'))
        with pytest.raises(IntegrityError):
            session.commit()


def test_concurrent_approvals_global(setup, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    admin, _ = setup
    one = proposal(admin, 'global1', 'first', None)
    two = proposal(admin, 'global2', 'second', None)
    barrier = Barrier(2)
    original = trust.conflicts

    def synchronized(*args, **kwargs):
        result = original(*args, **kwargs)
        barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(trust, 'conflicts', synchronized)
    def approve(p):
        try:
            return trust.resolve_proposal(admin, p['id'], action='approve', expected_revision=1)
        except HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(approve, (one, two)))
    assert sum(isinstance(x, dict) for x in outcomes) == 1
    assert 409 in outcomes


def test_postgresql_index_ddl():
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateIndex
    from gigamind.db.trust_models import AcceptedKnowledge

    index = next(i for i in AcceptedKnowledge.__table__.indexes if i.name == 'uq_trust_accepted_project_subject')
    ddl = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
    assert 'UNIQUE INDEX' in ddl
    assert 'coalesce' in ddl.lower()
    assert "status = 'accepted' AND subject IS NOT NULL" in ddl
