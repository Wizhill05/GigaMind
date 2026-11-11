import json

import pytest
from fastapi import HTTPException
from sqlmodel import create_engine

from gigamind.db.trust_models import initialize_trust_tables
from gigamind.security import Actor
from gigamind.services import context, trust


def test_scoped_accepted_search_and_budget(tmp_path, monkeypatch):
    engine = create_engine(f'sqlite:///{tmp_path}/db')
    initialize_trust_tables(engine)
    monkeypatch.setattr(trust, 'engine', engine)
    admin = Actor('admin', set(), None, True)
    agent = Actor('agent', {'memory:read'}, {'a'})

    def create(project, key, content, action='approve', subject=None):
        p = trust.create_proposal(admin, content=content, project_id=project, subject=subject,
            evidence=[{'source_type': 'file', 'source_id': key, 'quote': '🐈' * 200}], idempotency_key=key)['proposal']
        if action:
            return trust.resolve_proposal(admin, p['id'], action=action, expected_revision=1)
        return p

    old = create('a', 'old', 'purple old', subject='topic')['memory']
    p = trust.create_proposal(admin, content='purple new', project_id='a', subject='topic', evidence=[{'source_type': 'file', 'source_id': 'new', 'quote': '🐈' * 200}], idempotency_key='new')['proposal']
    new = trust.resolve_proposal(admin, p['id'], action='approve', expected_revision=1, supersedes=[old['id']])['memory']
    create('a', 'pending', 'purple pending', action=None)
    create('a', 'rejected', 'purple rejected', action='reject')
    create('b', 'other', 'purple other')
    create(None, 'global', 'purple global')
    rows = context.search_accepted(agent, 'purple', 'a')
    assert [r['id'] for r in rows] == [new['id']]
    assert rows[0]['evidence'][0]['source_id'] == 'new'
    assert context.search_accepted(agent, 'unmatched', 'a') == []
    for project in (None, 'b'):
        with pytest.raises(HTTPException) as exc:
            context.search_accepted(agent, 'purple', project)
        assert exc.value.status_code == 403
    for budget in (64, 512, 10000):
        result = context.get_context(agent, 'purple', 'a', budget)
        assert len(json.dumps(result, ensure_ascii=True).encode()) <= budget
    assert context.get_memory(agent, new['id'])['memory']['status'] == 'accepted'
