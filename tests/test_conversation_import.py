import json
import os
import subprocess
import sys

import pytest
from sqlmodel import Session, select
from gigamind.db.database import ConversationItem, MemoryItem, ProfileItem, engine, init_db
from gigamind.services import memory


@pytest.fixture(autouse=True)
def database(monkeypatch):
    from sqlmodel import SQLModel
    SQLModel.metadata.drop_all(engine)
    init_db()
    monkeypatch.setattr(memory, 'generate_embedding', lambda *a, **k: (_ for _ in ()).throw(AssertionError('provider called')))


def branch():
    def node(parent, role, content):
        return {'parent': parent, 'message': {'author': {'role': role}, 'content': {'parts': [content]}, 'create_time': 123}}
    return {'id': 'source', 'current_node': 'b', 'mapping': {'other': node('root', 'assistant', 'wrong'), 'b': node('a', 'assistant', 'late'), 'root': node(None, 'system', 'start'), 'a': node('root', 'user', 'prefer tea')}}


def rows():
    with Session(engine) as session:
        return session.exec(select(ConversationItem)).all()


def test_branch_and_atomic_validation():
    data = branch()
    assert memory.import_conversations_data([data])['ingested'] == 1
    messages = json.loads(rows()[0].messages_json)
    assert [(m['id'], m['role'], m['content'], m['created_at']) for m in messages] == [('root', 'system', 'start', 123), ('a', 'user', 'prefer tea', 123), ('b', 'assistant', 'late', 123)]
    assert rows()[0].embedding_json == '[]'
    for mutate in ('ambiguous', 'cycle', 'missing'):
        bad = branch()
        if mutate == 'ambiguous': del bad['current_node']
        elif mutate == 'cycle': bad['mapping']['a']['parent'] = 'b'
        else: bad['mapping']['a']['parent'] = 'absent'
        with pytest.raises(ValueError): memory.import_conversations_data([{'messages': [{'role': 'user', 'content': 'new'}]}, bad])
        assert len(rows()) == 1


def test_versions_roles_and_full_content():
    data = {'id': 'same-prefix-123456789', 'messages': [{'role': 'tool', 'content': [{'text': 'tool output'}]}, {'role': 'developer', 'content': 'x' * 50000 + 'late'}]}
    assert memory.import_conversations_data(data)['ingested'] == 1
    assert memory.import_conversations_data(data)['skipped'] == 1
    other = dict(data, id='same-prefix-123456780')
    assert memory.import_conversations_data(other)['ingested'] == 1
    changed = dict(data, messages=[{'role': 'human', 'content': 'changed'}])
    assert memory.import_conversations_data(changed)['ingested'] == 1
    no_id = {'chat_messages': [{'sender': 'mystery', 'content': [{'text': 'hello'}]}]}
    assert memory.import_conversations_data(no_id)['ingested'] == 1
    assert memory.import_conversations_data(no_id)['skipped'] == 1
    assert json.loads(rows()[0].messages_json)[1]['content'].endswith('late')
    with Session(engine) as session:
        assert not session.exec(select(MemoryItem)).all()
        assert not session.exec(select(ProfileItem)).all()


def test_cli(tmp_path):
    path = tmp_path / 'export.json'
    path.write_text(json.dumps([branch()]))
    env = dict(os.environ, DB_PATH=str(tmp_path / 'cli.db'), DATABASE_URL='', PYTHON_DOTENV_DISABLED='1')
    cmd = [sys.executable, '-m', 'gigamind.cli.importer', '--chatgpt', str(path)]
    first = subprocess.run(cmd, env=env, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    assert 'Imported 1' in first.stdout and 'Indexing pending' in first.stdout
    second = subprocess.run(cmd, env=env, capture_output=True, text=True)
    assert second.returncode == 0 and '1 duplicate' in second.stdout
    assert subprocess.run(cmd[:-1] + [str(tmp_path / 'missing')], env=env, capture_output=True).returncode != 0
