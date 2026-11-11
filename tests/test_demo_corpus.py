import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from sqlmodel import Session, create_engine, select

from gigamind.db.database import MemoryItem, ConversationItem
from gigamind.db.memory_index import MemoryIndexState
from gigamind.db.trust_models import AcceptedKnowledge
from gigamind.security import Actor
from gigamind.services import context, trust, memory


def test_demo_corpus(tmp_path, monkeypatch):
    path = tmp_path / 'demo.db'
    env = dict(os.environ, PYTHON_DOTENV_DISABLED='1', DATABASE_URL='', DB_PATH=str(tmp_path / 'untouched.db'))
    cmd = [sys.executable, '-m', 'gigamind.cli.demo', '--db', str(path)]
    subprocess.run(cmd, env=env, check=True, capture_output=True)
    digest = hashlib.sha256(path.read_bytes()).digest()
    assert subprocess.run(cmd, env=env, capture_output=True).returncode != 0
    assert hashlib.sha256(path.read_bytes()).digest() == digest
    assert not (tmp_path / 'untouched.db').exists()
    engine = create_engine(f'sqlite:///{path}')
    monkeypatch.setattr(trust, 'engine', engine)
    monkeypatch.setattr(memory, 'engine', engine)
    actor = Actor('test-admin', set(), None, True)
    with Session(engine) as session:
        assert len(session.exec(select(MemoryItem)).all()) == 64
        assert len(session.exec(select(ConversationItem)).all()) == 15
        indexes = session.exec(select(MemoryIndexState)).all()
        assert len(indexes) == 64 and all(i.index_status == 'pending' for i in indexes)
        records = session.exec(select(AcceptedKnowledge)).all()
        old = next(r for r in records if r.status == 'superseded')
        assert [r['status'] for r in trust.get_history(actor, old.id)['revisions']] == ['accepted', 'superseded']
    assert trust.list_proposals(actor)['total'] == 8
    assert len([p for p in trust.list_proposals(actor)['proposals'] if p['status'] == 'proposed']) == 3
    fixtures = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/demo/corpus.json').read_text())
    for case in fixtures['queries']:
        results = context.search_accepted(actor, case['query'], case['project'])
        if case['contains'] is None:
            assert results == []
        else:
            assert any(case['contains'] in row['content'] and row['evidence'] for row in results)
    assert context.get_context(actor, 'unrelated', None)['rules'][0]['kind'] == 'preference'
    assert memory.get_memories(page=2, limit=10, source_agent='synthetic-demo')['total'] == 64
    assert memory.get_memories(category='planning')['total'] == 8
    assert memory.get_conversations(page=2, limit=5, platform='demo-chat')['total'] == 7
