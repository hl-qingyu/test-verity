from threading import Lock
from time import monotonic

from app.core.errors import AppError

_login_windows: dict[str, tuple[float, int]] = {}
_login_lock = Lock()


def limit_requests(client_address: str, bucket: str = "login") -> None:
    # ponytail: per-process IP limit for local single-worker use; enforce at the
    # trusted reverse proxy before running multiple workers. Never trust X-Forwarded-For.
    address = bucket + ":" + client_address
    now = monotonic()
    with _login_lock:
        for key in [key for key, (end, _) in _login_windows.items() if end <= now]:
            del _login_windows[key]
        end, count = _login_windows.get(address, (now + 60, 0))
        if count >= 20 or (address not in _login_windows and len(_login_windows) >= 2048):
            raise AppError(429, "too_many_attempts", headers={"Retry-After": "60"})
        _login_windows[address] = (end, count + 1)
