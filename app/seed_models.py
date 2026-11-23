import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as _models  # noqa: F401
from app.core.database import Base, SessionLocal, engine
from app.models import AIModel, AIModelStatus
from app.schemas import AIModelCreate


SEED_FILE = Path(__file__).resolve().parent.parent / "examples" / "seed_models.json"


def load_seed_models(path: Path = SEED_FILE) -> list[AIModelCreate]:
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("Seed data must be a JSON array")

    models = [AIModelCreate.model_validate(record) for record in records]
    if any(model.status != AIModelStatus.DISABLED for model in models):
        raise ValueError("Seed models must remain disabled")
    return models


def seed_models(
    db: Session,
    *,
    tenant_id: str,
    models: Sequence[AIModelCreate],
) -> tuple[int, int]:
    if any(model.status != AIModelStatus.DISABLED for model in models):
        raise ValueError("Seed models must remain disabled")

    inserted = 0
    skipped = 0
    for model_data in models:
        existing = db.scalar(
            select(AIModel.id).where(
                AIModel.tenant_id == tenant_id,
                AIModel.name == model_data.name,
            )
        )
        if existing is not None:
            skipped += 1
            continue

        model = AIModel(
            tenant_id=tenant_id,
            name=model_data.name,
            provider=model_data.provider,
            model_identifier=model_data.model_identifier,
            capabilities=model_data.capabilities,
            status=model_data.status,
            priority=model_data.priority,
        )
        db.add(model)
        inserted += 1

    db.commit()
    return inserted, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed disabled NEXUS development models.")
    parser.add_argument("--tenant-id", required=True, help="Tenant that owns the seed models")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        inserted, skipped = seed_models(
            db,
            tenant_id=args.tenant_id,
            models=load_seed_models(),
        )
    print(f"Seed complete: {inserted} inserted, {skipped} skipped.")


if __name__ == "__main__":
    main()
