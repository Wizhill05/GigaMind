import json
import pytest
from fastapi import HTTPException
from sqlmodel import create_engine
from gigamind.db.migrations import migrate
from gigamind.security import Actor
from gigamind.services import coordination, context, trust


def test_coordination_persistence_scope_and_budget(tmp_path, monkeypatch):
    engine = create_engine(f'sqlite:///{tmp_path}/test.db')
    migrate(engine)
    monkeypatch.setattr(trust, 'engine', engine)
    admin = Actor('admin', set(), None, True)
    agent = Actor('agent', {'memory:read', 'memory:propose'}, {'a'})
    payload = dict(task_name='task', summary='report', status='working', project_id='a', verified_outcomes=['claim'], unresolved=[], next_actions=[], idempotency_key='one')
    first = coordination.save_handoff(agent, **payload)['handoff']
    assert first['writer_id'] == 'agent' and first['record_type'] == 'agent_report'
    assert coordination.save_handoff(agent, **payload)['handoff'] == first
    with pytest.raises(HTTPException) as exc:
        coordination.save_handoff(agent, **dict(payload, summary='changed'))
    assert exc.value.status_code == 409
    for project in (None, 'b'):
        with pytest.raises(HTTPException):
            coordination.save_handoff(agent, **dict(payload, project_id=project))
    p = trust.create_proposal(admin, content='accepted', project_id='a', evidence=[], idempotency_key='p')['proposal']
    memory = trust.resolve_proposal(admin, p['id'], action='approve', expected_revision=1)['memory']
    issue = coordination.report_memory_issue(agent, memory_id=memory['id'], project_id='a', reason='incorrect', idempotency_key='i')['issue']
    assert coordination.list_issues(Actor('other', {'memory:read'}, {'a'}), 'a')['total'] == 0
    assert coordination.resolve_issue(admin, issue['id'], status='resolved', expected_revision=1)['issue']['revision'] == 2
    assert trust.get_memory(agent, memory['id'])['memory'] == memory
    assert context.get_context(agent, 'accepted', 'a', 64)['handoff'] is None
    result = context.get_context(agent, 'accepted', 'a', 10000)
    assert result['handoff']['id'] == first['id']
    assert len(json.dumps(result, ensure_ascii=True).encode()) <= 10000
    with pytest.raises(HTTPException):
        coordination.save_handoff(agent, **dict(payload, writer_id='forged'))


def test_http_and_mcp(server):
    import asyncio
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    headers = {'Authorization': 'Bearer test-master-key'}
    payload = dict(task_name='http', summary='report', status='working', project_id='p', verified_outcomes=[], unresolved=[], next_actions=[], idempotency_key='http')
    response = httpx.post(server + '/api/v1/review/handoffs', headers=headers, json=payload, trust_env=False)
    assert response.status_code == 200
    assert httpx.post(server + '/api/v1/review/handoffs', headers=headers, json=dict(payload, writer_id='forged'), trust_env=False).status_code == 422
    assert httpx.get(server + '/api/v1/review/handoffs/latest', headers=headers, params={'project_id': 'p'}, trust_env=False).json()['handoff']['id'] == response.json()['handoff']['id']
    async def exercise():
        async with httpx.AsyncClient(headers=headers, trust_env=False) as client:
            async with streamable_http_client(server + '/mcp', http_client=client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool('save_handoff', dict(payload, idempotency_key='mcp'))
                    assert not result.isError and result.structuredContent['handoff']['writer_id']
                    invalid = await session.call_tool('save_handoff', dict(payload, writer_id='forged'))
                    assert invalid.isError
    asyncio.run(exercise())

from test_mcp_transport import server


def test_concurrent_idempotency_and_issue_scope(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    engine = create_engine(f'sqlite:///{tmp_path}/concurrent.db', connect_args={'timeout': 10})
    migrate(engine)
    monkeypatch.setattr(trust, 'engine', engine)
    admin = Actor('admin', set(), None, True)
    agent = Actor('agent', {'memory:read', 'memory:propose'}, {'a'})
    payload = dict(task_name='task', summary='summary', status='done', project_id='a', verified_outcomes=[], unresolved=[], next_actions=[], idempotency_key='shared')
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: coordination.save_handoff(agent, **payload), range(4)))
    assert len({r['handoff']['id'] for r in results}) == 1
    p = trust.create_proposal(admin, content='fact', project_id='b', evidence=[], idempotency_key='p')['proposal']
    memory = trust.resolve_proposal(admin, p['id'], action='approve', expected_revision=1)['memory']
    with pytest.raises(HTTPException):
        coordination.report_memory_issue(agent, memory_id=memory['id'], reason='wrong', project_id='a', idempotency_key='i')
    with pytest.raises(HTTPException):
        coordination.report_memory_issue(Actor('reader', {'memory:read'}, {'a'}), memory_id=memory['id'], reason='wrong', project_id='a', idempotency_key='i')
