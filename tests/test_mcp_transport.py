import asyncio
import os
import socket
import subprocess
import sys
import time

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


@pytest.fixture
def server(tmp_path):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = {'PATH': os.environ['PATH'], 'PYTHONPATH': os.getcwd(), 'DB_PATH': str(tmp_path / 'test.db'),
           'GIGAMIND_API_KEY': 'test-master-key', 'PYTHON_DOTENV_DISABLED': '1'}
    proc = subprocess.Popen([sys.executable, '-c', "import gigamind.main; import gigamind.services.memory as m; import uvicorn; m.generate_embedding = lambda *a, **k: []; m.add_memory('purple aardvark'); uvicorn.run(gigamind.main.app, host='127.0.0.1', port=" + str(port) + " )"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f'http://127.0.0.1:{port}'
    try:
        for _ in range(100):
            try:
                if httpx.get(url + '/health/live', trust_env=False).status_code == 200:
                    break
            except httpx.ConnectError:
                time.sleep(.05)
        else:
            raise RuntimeError('Server did not start')
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_transport(server):
    admin = {'Authorization': 'Bearer test-master-key'}
    assert httpx.post(server + '/mcp', json={}, trust_env=False).status_code == 401
    assert httpx.get(server + '/health/ready', trust_env=False).json() == {'status': 'ready'}
    assert httpx.get(server + '/api/v1/memories', headers=admin, trust_env=False, params={'page': 0}).status_code == 422
    filtered = httpx.get(server + '/api/v1/memories', headers=admin, params={'q': 'unmatched'}, trust_env=False).json()
    assert filtered['memories'] == []
    created = httpx.post(server + '/api/v1/admin/clients', headers=admin, trust_env=False, json={'name': 'reader', 'scopes': ['memory:read'], 'project_ids': ['p']}).json()

    async def exercise():
        async with httpx.AsyncClient(trust_env=False, headers=admin) as client:
            async with streamable_http_client(server + '/mcp', http_client=client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    assert {t.name for t in (await session.list_tools()).tools} == {'get_user_profile', 'search_memory', 'get_server_status'}
                    assert (await session.call_tool('get_server_status', {})).structuredContent == {'status': 'online'}
                    assert (await session.call_tool('get_user_profile', {})).structuredContent == {'rules': []}
                    found = await session.call_tool('search_memory', {'query': 'purple aardvark'})
                    assert not found.isError and found.structuredContent['results'][0]['id'].startswith('mem_')
                    assert found.structuredContent['results'][0]['id'] in found.content[0].text
                    assert (await session.call_tool('search_memory', {'query': '', 'limit': 101})).isError
                    assert (await session.call_tool('delete_memory', {})).isError
        async with httpx.AsyncClient(trust_env=False, headers={'Authorization': 'Bearer ' + created['token']}) as client:
            async with streamable_http_client(server + '/mcp', http_client=client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    assert (await session.call_tool('get_server_status', {})).structuredContent == {'status': 'online'}
                    assert (await session.call_tool('get_user_profile', {})).isError
                    assert httpx.post(server + '/api/v1/admin/clients/' + created['client']['id'] + '/revoke', headers=admin, trust_env=False).status_code == 200
                    response = await client.post(server + '/mcp', json={
                        'jsonrpc': '2.0', 'id': 99, 'method': 'tools/call',
                        'params': {'name': 'get_server_status', 'arguments': {}}
                    })
                    assert response.status_code == 401
    asyncio.run(exercise())
