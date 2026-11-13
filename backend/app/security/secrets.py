from cryptography.fernet import Fernet

from app.core.config import Settings
from app.core.errors import AppError


def credential_cipher(error_code: str) -> Fernet:
    # Preserve the existing master key and ciphertexts; rotation is a separate migration.
    try:
        return Fernet(Settings().ai_encryption_key.get_secret_value().encode("ascii"))
    except (ValueError, UnicodeError):
        raise AppError(503, error_code) from None
