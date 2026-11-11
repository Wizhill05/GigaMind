from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlmodel import SQLModel, Session, create_engine

from gigamind.services import jobs


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.db'}", connect_args={"timeout": 10})
    SQLModel.metadata.create_all(engine)
    return engine


def test_concurrent_latest_and_old_repeat(engine):
    barrier = Barrier(2)
    def enqueue(key):
        barrier.wait()
        return jobs.enqueue("index_file", {"key": "file"}, key, engine=engine)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(enqueue, ["one", "two"]))
    states = [jobs.status(j.id, engine=engine).state for j in (first, second)]
    assert sorted(states) == ["cancelled", "queued"]
    old = (first, second)[states.index("cancelled")]
    current = (first, second)[states.index("queued")]
    assert jobs.enqueue("index_file", {"key": "file"}, old.idempotency_key, engine=engine).id == old.id
    assert jobs.status(current.id, engine=engine).state == "queued"
    with pytest.raises(jobs.Conflict):
        jobs.enqueue("index_file", {"key": "file"}, old.idempotency_key, max_attempts=4, engine=engine)
    assert jobs.status(current.id, engine=engine).state == "queued"


def test_forget_and_supersession_fence(engine):
    first = jobs.enqueue("index_file", {"key": "file"}, engine=engine)
    lease = jobs.claim(engine=engine)
    second = jobs.enqueue("index_file", {"key": "file"}, engine=engine)
    with Session(engine) as session, pytest.raises(jobs.PermanentFailure):
        jobs.JobLease(first.id, lease.lease_token).publication_guard(session)
    assert jobs.forget_resource("file", engine=engine) == 1
    assert jobs.forget_resource("file", engine=engine) == 0
    engine.dispose()
    with pytest.raises(jobs.Conflict):
        jobs.enqueue("index_file", {"key": "file"}, engine=engine)
    assert jobs.status(second.id, engine=engine).state == "cancelled"
