from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import TenantSecret


class SecretStoreError(RuntimeError):
    pass


class SecretNotFoundError(LookupError):
    pass


def _fernet() -> Fernet:
    key = settings.secret_encryption_key
    if key is None:
        raise SecretStoreError("Secret encryption is not configured")
    try:
        return Fernet(key.get_secret_value().encode("ascii"))
    except (UnicodeEncodeError, TypeError, ValueError) as exc:
        raise SecretStoreError("Secret encryption key is invalid") from exc


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    try:
        plaintext = _fernet().decrypt(ciphertext.encode("ascii"))
        return plaintext.decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as exc:
        raise SecretStoreError("Stored secret cannot be decrypted") from exc


def resolve_secret(db: Session, *, tenant_id: str, name: str) -> str:
    secret = db.scalar(
        select(TenantSecret).where(
            TenantSecret.tenant_id == tenant_id,
            TenantSecret.name == name,
        )
    )
    if secret is None:
        raise SecretNotFoundError(f"Secret {name!r} was not found")
    return decrypt_secret(secret.ciphertext)
