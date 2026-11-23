from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from jose import jwt
from pydantic import ValidationError
from cryptography.fernet import Fernet

from app.core.config import Settings
from app.security import require_permission


def production_settings() -> Settings:
    return Settings(
        environment="production",
        jwt_secret="a" * 32,
        jwt_issuer="nexus",
        jwt_audience="nexus-api",
        secret_encryption_key=Fernet.generate_key().decode("ascii"),
    )


def test_production_settings_require_strong_identity_configuration():
    with pytest.raises(ValidationError):
        Settings(environment="production", jwt_secret="change-this-in-production")

    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            jwt_secret="a" * 32,
        )

    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            jwt_secret="a" * 32,
            jwt_issuer="nexus",
            jwt_audience="nexus-api",
        )


def test_production_jwt_requires_exp_issuer_and_audience():
    settings = production_settings()
    dependency = require_permission("nexus.command.read")

    token = jwt.encode(
        {
            "sub": "test-user",
            "role": "operator",
            "tenant_id": "tenant-a",
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    import app.security

    original = app.security.settings
    app.security.settings = settings
    try:
        with pytest.raises(HTTPException) as exc_info:
            dependency(
                authorization=f"Bearer {token}",
                x_tenant_id="tenant-a",
            )
        assert exc_info.value.status_code == 401

        valid_token = jwt.encode(
            {
                "sub": "test-user",
                "role": "operator",
                "tenant_id": "tenant-a",
                "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
                "iss": "nexus",
                "aud": "nexus-api",
            },
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
        assert dependency(
            authorization=f"Bearer {valid_token}",
            x_tenant_id="tenant-a",
        ) == ("test-user", "tenant-a")
    finally:
        app.security.settings = original
