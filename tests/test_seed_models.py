import pytest

from app.models import AIModel, AIModelStatus
from app.schemas import AIModelCreate
from app.seed_models import load_seed_models, seed_models


def test_seed_models_are_disabled_and_idempotent(db_session):
    models = load_seed_models()

    inserted, skipped = seed_models(
        db_session,
        tenant_id="seed-tenant",
        models=models,
    )
    assert inserted == len(models)
    assert skipped == 0

    inserted_again, skipped_again = seed_models(
        db_session,
        tenant_id="seed-tenant",
        models=models,
    )
    assert inserted_again == 0
    assert skipped_again == len(models)

    tenant_models = db_session.query(AIModel).filter_by(tenant_id="seed-tenant").all()
    assert all(model.status == AIModelStatus.DISABLED for model in tenant_models)


def test_seed_models_can_be_added_to_a_separate_tenant(db_session):
    models = load_seed_models()
    seed_models(db_session, tenant_id="tenant-a", models=models)
    seed_models(db_session, tenant_id="tenant-b", models=models)

    assert db_session.query(AIModel).count() == len(models) * 2


def test_seed_models_reject_enabled_records(db_session):
    with pytest.raises(ValueError, match="must remain disabled"):
        seed_models(
            db_session,
            tenant_id="seed-tenant",
            models=[
                AIModelCreate(
                    name="enabled-model",
                    provider="openai-compatible",
                    model_identifier="some-model",
                )
            ],
        )
