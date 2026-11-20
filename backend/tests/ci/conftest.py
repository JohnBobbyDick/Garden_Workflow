import socket
import sys
import threading
import time

import pytest
import uvicorn

from app.config import REPO_ROOT, get_settings
from tests.api.conftest import alice, bob, client, db  # noqa: F401 - shared API fixtures

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import mock_scm  # noqa: E402


@pytest.fixture
def scm(monkeypatch):
    srv, state = mock_scm.start()
    hp = f"127.0.0.1:{srv.server_address[1]}"
    monkeypatch.setenv("APP_SSRF_ALLOW_HOSTS", hp)
    get_settings.cache_clear()
    yield f"http://{hp}", state
    srv.shutdown()
    get_settings.cache_clear()


@pytest.fixture
def live_server(db):  # noqa: F811 - pytest fixture injection
    """A real uvicorn server (same test DB, in-process worker) for the stdlib CLI."""
    from app.main import create_app

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    get_settings().inprocess_worker = True
    get_settings().worker_poll_seconds = 0.2
    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    th.join(timeout=10)
    get_settings().inprocess_worker = False
