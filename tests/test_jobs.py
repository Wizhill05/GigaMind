from datetime import datetime, timedelta, timezone
import pytest
from sqlmodel import SQLModel, create_engine
from gigamind.services import jobs


def test_queue_lifecycle(tmp_path, monkeypatch):
    engine = create_engine(f'sqlite:///{tmp_path / "jobs.db"}', connect_args={'check_same_thread': False})
    jobs.Job.__table__.create(engine)
    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    clock = lambda: now[0]
    j = jobs.enqueue('index_file', {'key': 'files/a'}, 'unique', engine=engine, clock=clock)
    engine.dispose()
    assert jobs.status(j.id, engine=engine).state == 'queued'
    assert jobs.enqueue('index_file', {'key': 'files/a'}, 'unique', engine=engine, clock=clock).id == j.id
    with pytest.raises(jobs.Conflict):
        jobs.enqueue('index_file', {'key': 'files/b'}, 'unique', engine=engine, clock=clock)
    first = jobs.claim(engine=engine, clock=clock, lease_seconds=10)
    assert jobs.claim(engine=engine, clock=clock) is None
    assert jobs.heartbeat(j.id, first.lease_token, engine=engine, clock=clock, lease_seconds=10)
    now[0] += timedelta(seconds=11)
    second = jobs.claim(engine=engine, clock=clock)
    assert second.lease_token != first.lease_token
    assert not jobs.guarded(j.id, first.lease_token, {'state': 'completed'}, engine=engine, clock=clock)
    assert jobs.cancel(j.id, engine=engine, clock=clock)
    assert not jobs.guarded(j.id, second.lease_token, {'state': 'completed'}, engine=engine, clock=clock)


def test_worker_retry(tmp_path, monkeypatch):
    engine = create_engine(f'sqlite:///{tmp_path / "jobs.db"}', connect_args={'check_same_thread': False})
    jobs.Job.__table__.create(engine)
    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    clock = lambda: now[0]
    calls = []
    from gigamind.services import indexing
    def handler(key, publication_guard):
        calls.append(key)
        if len(calls) == 1:
            raise RuntimeError('secret')
        return {'status': 'completed'}
    monkeypatch.setattr(indexing, 'reindex_storage_file_by_key', handler, raising=False)
    j = jobs.enqueue('index_file', {'key': 'a'}, engine=engine, clock=clock)
    assert jobs.run_once(engine=engine, clock=clock).state == 'retrying'
    assert 'secret' not in jobs.status(j.id, engine=engine).error
    assert jobs.run_once(engine=engine, clock=clock) is None
    now[0] += timedelta(seconds=1)
    assert jobs.run_once(engine=engine, clock=clock).state == 'completed'


def test_concurrency_and_fencing(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlmodel import Session, select

    engine = create_engine(f'sqlite:///{tmp_path / "race.db"}', connect_args={'check_same_thread': False, 'timeout': 10})
    jobs.Job.__table__.create(engine)
    barrier = Barrier(2)
    def enqueue():
        barrier.wait()
        return jobs.enqueue('index_file', {'key': 'a'}, 'same', engine=engine).id
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: enqueue(), range(2)))
    assert ids[0] == ids[1]
    with Session(engine) as session:
        assert len(session.exec(select(jobs.Job)).all()) == 1
    barrier = Barrier(2)
    def claim():
        barrier.wait()
        return jobs.claim(engine=engine)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: claim(), range(2)))
    assert sum(c is not None for c in claims) == 1
    engine.dispose()
    assert jobs.status(ids[0], engine=engine).state == 'running'
    assert jobs.cancel_resource('ab', engine=engine) == 0
    assert jobs.cancel_resource('a', engine=engine) == 1
    lease = next(c for c in claims if c)
    with Session(engine) as session, pytest.raises(jobs.PermanentFailure):
        jobs.JobLease(lease.id, lease.lease_token).publication_guard(session)


def test_expiry_and_terminal(tmp_path):
    from sqlmodel import Session
    engine = create_engine(f'sqlite:///{tmp_path / "expiry.db"}')
    jobs.Job.__table__.create(engine)
    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    clock = lambda: now[0]
    job = jobs.enqueue('index_file', {'key': 'a'}, max_attempts=2, engine=engine, clock=clock)
    first = jobs.claim(engine=engine, clock=clock, lease_seconds=1)
    now[0] += timedelta(seconds=2)
    second = jobs.claim(engine=engine, clock=clock, lease_seconds=1)
    assert not jobs.heartbeat(job.id, first.lease_token, engine=engine, clock=clock)
    assert not jobs.guarded(job.id, first.lease_token, {'state': 'completed'}, engine=engine, clock=clock)
    with Session(engine) as session, pytest.raises(jobs.PermanentFailure):
        jobs.JobLease(job.id, first.lease_token, clock).publication_guard(session)
    now[0] += timedelta(seconds=2)
    assert jobs.claim(engine=engine, clock=clock) is None
    assert jobs.status(job.id, engine=engine).state == 'failed'


def test_real_heartbeat(tmp_path, monkeypatch):
    import threading
    engine = create_engine(f'sqlite:///{tmp_path / "heartbeat.db"}', connect_args={'check_same_thread': False})
    jobs.Job.__table__.create(engine)
    renewed = threading.Event()
    original = jobs.heartbeat
    def heartbeat(*args, **kwargs):
        result = original(*args, **kwargs)
        if result:
            renewed.set()
        return result
    monkeypatch.setattr(jobs, 'heartbeat', heartbeat)
    from gigamind.services import indexing
    def handler(key, publication_guard):
        assert renewed.wait(3)
        return {'status': 'completed'}
    monkeypatch.setattr(indexing, 'reindex_storage_file_by_key', handler, raising=False)
    jobs.enqueue('index_file', {'key': 'a'}, engine=engine)
    assert jobs.run_once(engine=engine, lease_seconds=1).state == 'completed'


@pytest.mark.parametrize('duration', [0, -1, float('nan'), float('inf'), 86401, True])
def test_invalid_lease(tmp_path, duration):
    engine = create_engine(f'sqlite:///{tmp_path / "bounds.db"}')
    jobs.Job.__table__.create(engine)
    with pytest.raises(ValueError):
        jobs.claim(engine=engine, lease_seconds=duration)


def test_input_bounds(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path / "inputs.db"}')
    jobs.Job.__table__.create(engine)
    for payload in ({'key': ''}, {'key': 'x' * 4097}, {'key': 'a', 'other': 1}):
        with pytest.raises(ValueError):
            jobs.enqueue('index_file', payload, engine=engine)
    for options in ({'idempotency_key': ' '}, {'idempotency_key': 'x' * 256}, {'max_attempts': 0}, {'max_attempts': True}):
        with pytest.raises(ValueError):
            jobs.enqueue('index_file', {'key': 'a'}, engine=engine, **options)


def test_publication_guard_and_permanent_failure(tmp_path, monkeypatch):
    from sqlmodel import Session
    from gigamind.services import indexing
    engine = create_engine(f'sqlite:///{tmp_path / "publication.db"}')
    jobs.Job.__table__.create(engine)
    job = jobs.enqueue('index_file', {'key': 'a'}, engine=engine)
    lease = jobs.claim(engine=engine)
    with Session(engine) as session:
        jobs.JobLease(job.id, lease.lease_token).publication_guard(session)
        session.commit()
    jobs.cancel(job.id, engine=engine)
    with Session(engine) as session, pytest.raises(jobs.PermanentFailure):
        jobs.JobLease(job.id, lease.lease_token).publication_guard(session)
    monkeypatch.setattr(indexing, 'reindex_storage_file_by_key', lambda key, publication_guard: {'status': 'unsupported'}, raising=False)
    jobs.enqueue('index_file', {'key': 'b'}, engine=engine)
    assert jobs.run_once(engine=engine).state == 'failed'
