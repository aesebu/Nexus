from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import app.worker as worker
from app.models import WorkerHeartbeat
from app.worker_monitoring import (
    WORKER_HEARTBEAT_STALE_SECONDS,
    record_worker_heartbeat,
)


def test_worker_health_endpoint_reports_only_fresh_running_workers(client, db_session):
    now = datetime.now(timezone.utc)
    db_session.add(
        WorkerHeartbeat(
            worker_id="worker-a",
            status="RUNNING",
            started_at=now,
            last_seen_at=now,
        )
    )
    db_session.commit()

    healthy = client.get("/health/worker")
    assert healthy.status_code == 200
    assert healthy.json() == {"status": "healthy", "active_workers": 1}

    heartbeat = db_session.get(WorkerHeartbeat, "worker-a")
    heartbeat.last_seen_at = now - timedelta(
        seconds=WORKER_HEARTBEAT_STALE_SECONDS + 1
    )
    db_session.commit()
    stale = client.get("/health/worker")
    assert stale.status_code == 503
    assert stale.json() == {"status": "unavailable", "active_workers": 0}

    heartbeat.status = "STOPPED"
    heartbeat.last_seen_at = now
    db_session.commit()
    stopped = client.get("/health/worker")
    assert stopped.status_code == 503
    assert stopped.json() == {"status": "unavailable", "active_workers": 0}

    assert client.get("/health/ready").json() == {"status": "ready"}


def test_worker_heartbeat_recording_updates_state(db_session):
    start = datetime.now(timezone.utc)
    record_worker_heartbeat(
        db_session,
        worker_id="worker-b",
        status="RUNNING",
        now=start,
    )
    heartbeat = db_session.get(WorkerHeartbeat, "worker-b")
    assert heartbeat.started_at.replace(tzinfo=timezone.utc) == start
    assert heartbeat.last_seen_at.replace(tzinfo=timezone.utc) == start

    next_beat = start + timedelta(seconds=10)
    record_worker_heartbeat(
        db_session,
        worker_id="worker-b",
        status="STOPPED",
        now=next_beat,
    )
    assert heartbeat.status == "STOPPED"
    assert heartbeat.started_at.replace(tzinfo=timezone.utc) == start
    assert heartbeat.last_seen_at.replace(tzinfo=timezone.utc) == next_beat


def test_production_worker_does_not_create_database_schema(monkeypatch):
    calls = []
    monkeypatch.setattr(worker, "settings", SimpleNamespace(environment="production"))
    monkeypatch.setattr(
        worker.Base.metadata,
        "create_all",
        lambda **kwargs: calls.append(kwargs),
    )

    worker.initialize_worker_database()

    assert calls == []


def test_worker_health_endpoint_requires_a_fresh_heartbeat(client, db_session):
    heartbeat = WorkerHeartbeat(
        worker_id="worker-c",
        status="RUNNING",
        started_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
    )
    db_session.add(heartbeat)
    db_session.commit()

    assert client.get("/health/worker").status_code == 200
    assert client.get("/health/ready").status_code == 200
