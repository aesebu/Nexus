import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.core.config import settings
from app.main import app


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///./test.db")
    TestingSessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestingSessionLocal() as db:
        yield db
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def token(
    role: str = "operator",
    tenant_id: str = "tenant-a",
    subject: str = "test-user",
) -> str:
    return jwt.encode(
        {"sub": subject, "role": role, "tenant_id": tenant_id},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def auth_headers(
    role: str = "operator",
    tenant_id: str = "tenant-a",
    subject: str = "test-user",
) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token(role=role, tenant_id=tenant_id, subject=subject)}",
        "X-Tenant-ID": tenant_id,
    }
