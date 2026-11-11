import json

import pytest
from sqlalchemy import create_engine
from sqlmodel import Session

from gigamind.db.database import ConversationItem
from gigamind.services import memory


@pytest.fixture
def database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'search.sqlite'}")
    ConversationItem.__table__.create(engine)
    monkeypatch.setattr(memory, 'engine', engine)
    monkeypatch.setattr(memory, 'is_postgres', False)
    monkeypatch.setattr(memory, 'generate_embedding', lambda *args: (_ for _ in ()).throw(RuntimeError('offline')))
    yield engine
    engine.dispose()


def add(engine, ident, messages, platform='ChatGPT', source='GPT', vector=None):
    with Session(engine) as session:
        session.add(ConversationItem(id=ident, platform=platform, source_agent=source,
            title='ordinary', summary='ordinary', created_at='2024',
            messages_json=json.dumps(messages), embedding_json=json.dumps(vector or [])))
        session.commit()


def test_complete_transcripts_and_filters(database):
    for i in range(65):
        add(database, f'{i:03}', [{'role': 'user', 'content': 'ordinary'}])
    messages = [{'role': 'user', 'content': 'ordinary'} for _ in range(100)]
    messages.append({'role': 'assistant', 'content': 'x' * 500 + ' cafézebra', 'id': 'node-100', 'created_at': 'yesterday'})
    add(database, 'zzz', messages)
    add(database, 'other', messages, platform='Claude', source='other')
    result = memory.search_conversations('cafézebra', platform='chatgpt', source_agent='gpt')
    assert [x['id'] for x in result] == ['zzz']
    assert result[0]['retrieval_method'] == 'lexical'
    assert result[0]['evidence'][0] == {'role': 'assistant', 'index': 100, 'text': 'x' * 99 + ' cafézebra', 'id': 'node-100', 'created_at': 'yesterday'}
    assert memory.search_conversations('absent') == []
    assert memory.search_conversations('  ') == []
    assert memory.search_conversations('cafézebra', platform='claude', source_agent='gpt') == []


def test_order_limit_and_vectors(database, monkeypatch):
    monkeypatch.setattr(memory.embedding_config, 'DEFAULT_DIM', 2)
    monkeypatch.setattr(memory, 'generate_embedding', lambda *args: [1.0, 0.0])
    add(database, 'b', [{'role': 'user', 'content': 'needle'}])
    add(database, 'a', [{'role': 'user', 'content': 'needle'}])
    add(database, 'semantic', [], vector=[1.0, 0.0])
    add(database, 'invalid', [], vector=[True, 0])
    rows = memory.search_conversations('needle', limit=2)
    assert [row['id'] for row in rows] == ['a', 'b']
    rows = memory.search_conversations('unrelated', limit=1000)
    assert [row['id'] for row in rows] == ['semantic']
    assert rows[0]['retrieval_method'] == 'vector'
    monkeypatch.setattr(memory, 'generate_embedding', lambda *args: [float('nan'), 0])
    assert memory.search_conversations('unrelated') == []
