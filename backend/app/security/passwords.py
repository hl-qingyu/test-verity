import hashlib
import hmac
import secrets


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=32768, r=8, p=3, maxmem=64 * 1024 * 1024
    )
    return f"scrypt$32768$8$3${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if (algorithm, n, r, p) != ("scrypt", "32768", "8", "3"):
            return False
        if len(salt) != 32 or len(expected) != 128:
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt),
            n=32768,
            r=8,
            p=3,
            maxmem=64 * 1024 * 1024,
        )
        return hmac.compare_digest(digest, bytes.fromhex(expected))
    except (ValueError, UnicodeError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
