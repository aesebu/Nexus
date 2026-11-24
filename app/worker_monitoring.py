import sys
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import WorkerHeartbeat

WORKER_HEARTBEAT_INTERVAL_SECONDS = 10
WORKER_HEARTBEAT_STALE_SECONDS = 360


def record_worker_heartbeat(
    db: Session,
    *,
    worker_id: str,
    status: Literal["RUNNING", "STOPPED"],
    now: datetime | None = None,
) -> None:
    timestamp = now or datetime.now(timezone.utc)
    heartbeat = db.get(WorkerHeartbeat, worker_id)
    if heartbeat is None:
        heartbeat = WorkerHeartbeat(
            worker_id=worker_id,
            status=status,
            started_at=timestamp,
            last_seen_at=timestamp,
        )
        db.add(heartbeat)
    else:
        heartbeat.status = status
        heartbeat.last_seen_at = timestamp
    db.commit()


def active_worker_count(
    db: Session,
    *,
    now: datetime | None = None,
) -> int:
    timestamp = now or datetime.now(timezone.utc)
    cutoff = timestamp - timedelta(seconds=WORKER_HEARTBEAT_STALE_SECONDS)
    return db.scalar(
        select(func.count())
        .select_from(WorkerHeartbeat)
        .where(
            WorkerHeartbeat.status == "RUNNING",
            WorkerHeartbeat.last_seen_at >= cutoff,
        )
    ) or 0


def main() -> None:
    with SessionLocal() as db:
        sys.exit(0 if active_worker_count(db) > 0 else 1)


if __name__ == "__main__":
    main()
