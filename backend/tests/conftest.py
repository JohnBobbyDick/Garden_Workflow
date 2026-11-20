import base64
import os
import tempfile

import pytest

# Isolate every test session: own data dir, master key and JWT secret (never the developer's backend/data).
_SESSION_DIR = tempfile.mkdtemp(prefix="aisw-tests-")
os.environ.setdefault("APP_ENV", "test")
os.environ["APP_DATA_DIR"] = _SESSION_DIR
os.environ["APP_DATABASE_URL"] = f"sqlite:///{_SESSION_DIR.replace(os.sep, '/')}/default.db"
os.environ.setdefault("APP_MASTER_KEY", base64.b64encode(os.urandom(32)).decode())
os.environ.setdefault("APP_JWT_SECRET", base64.b64encode(os.urandom(32)).decode())


def symlink_or_skip(target, link) -> None:
    """Create a symlink; skip the test where the OS forbids it (Windows without developer mode)."""
    try:
        os.symlink(target, link)
    except OSError as exc:  # pragma: no cover - platform dependent
        pytest.skip(f"symlinks unavailable on this platform: {exc}")
