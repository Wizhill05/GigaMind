import base64

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from gigamind.db.database import MemoryItem, ProfileItem
from gigamind.main import app, API_KEY
from gigamind.services import memory


@pytest.fixture
def source_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'source.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(memory, "engine", engine)
    monkeypatch.setattr(memory, "is_postgres", False)
    with Session(engine) as session:
        for i in range(75):
            session.add(MemoryItem(id=str(i), content="ordinary filler", category="other", source_agent="a", created_at="now", last_accessed="now"))
        session.add(MemoryItem(id="late", content="filler " * 2000 + "稀有 xy", category="wanted", source_agent="b", created_at="now", last_accessed="now", attachments_json='[{"key":"example","filename":"e"}]'))
        session.add(ProfileItem(id="profile", key="稀有", value="xy", category="wanted", source_agent="b", updated_at="now"))
        session.commit()
    yield engine
    engine.dispose()


def test_authenticated_complete_filtered_lexical_search(source_db):
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {API_KEY}"}
    def search(query, **kwargs):
        response = client.post('/api/v1/search_memory', headers=headers, json={"query": query, "scope": "memories", **kwargs})
        assert response.status_code == 200, response.text
        return response.json()['results']
    results = search('稀有', category='wanted', source_agent='b', limit=2)
    assert {r['id'] for r in results} == {'late', 'profile'}
    assert all(r['retrieval_method'] == 'lexical' and 'vector_score' not in r for r in results)
    assert next(r for r in results if r['id'] == 'late')['attachments'][0]['key'] == 'example'
    assert search('xy', category='wanted', source_agent='b')
    assert search('稀有', category='other') == []
    assert search('termabsent') == []


def test_provider_failure_and_invalid_vector(source_db, monkeypatch):
    def fail(**kwargs):
        raise memory.embedding_config.EmbeddingUnavailable('provider unavailable')
    monkeypatch.setattr(memory, 'generate_embedding', fail)
    assert memory.search_memory('稀有', scope='memories')
    monkeypatch.setattr(memory, 'generate_embedding', lambda **kwargs: [float('nan')])
    assert memory.search_memory('稀有', scope='memories')
    assert memory.search_memory('absent', scope='memories') == []


def test_image_validation_and_unavailable(source_db):
    jpeg = base64.b64encode(b'\xff\xd8\xff' + b'fake').decode()
    with pytest.raises(RuntimeError, match='GEMINI_API_KEY'):
        memory.search_memory(query_image_base64=jpeg)
    with pytest.raises(ValueError):
        memory.search_memory(query_image_base64='not base64!')
