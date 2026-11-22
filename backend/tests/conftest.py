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
# The platform-default LLM (LLM_ENABLED / NVIDIA_* in the environment or backend/.env) must never leak into tests.
os.environ["LLM_ENABLED"] = "false"


@pytest.fixture(scope="session", autouse=True)
def isolate_test_settings():
    from app.ai.pool import LLMEnv, get_llm_env
    from app.config import Settings, get_settings

    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(Settings.model_config, "env_file", None)
        patch.setitem(LLMEnv.model_config, "env_file", None)
        for field in LLMEnv.model_fields:
            if field != "llm_enabled":
                patch.delenv(field.upper(), raising=False)
        get_llm_env.cache_clear()
        get_settings.cache_clear()
        yield
        get_llm_env.cache_clear()
        get_settings.cache_clear()


def symlink_or_skip(target, link) -> None:
    """Create a symlink; skip the test where the OS forbids it (Windows without developer mode)."""
    try:
        os.symlink(target, link)
    except OSError as exc:  # pragma: no cover - platform dependent
        pytest.skip(f"symlinks unavailable on this platform: {exc}")


@pytest.fixture
def nvidia_server(monkeypatch):
    """Exercise the fixed HTTPS contract on an isolated real server, without operator keys or network access."""
    from app.ai.providers import base
    from app.core.ssrf import safe_request
    from tests.ai.fake_llm import make_server

    srv, script, hp = make_server("nvidia")

    async def local_request(method, url, **kwargs):
        assert url == "https://integrate.api.nvidia.com/v1/chat/completions"
        assert kwargs["max_redirects"] == 0
        kwargs["allow_hosts"] = kwargs["allow_hosts"] | {hp}
        return await safe_request(method, f"http://{hp}/v1/chat/completions", **kwargs)

    monkeypatch.setattr(base, "safe_request", local_request)
    try:
        yield script, hp
    finally:
        srv.shutdown()


@pytest.fixture
def smtp_server(monkeypatch):
    import socket

    from aiosmtpd.controller import Controller

    from app.config import get_settings
    from tests.nodes.test_notify_nodes import MailSink

    handler = MailSink()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    ctl = Controller(handler, hostname="127.0.0.1", port=port, auth_require_tls=False, server_hostname="localhost")
    ctl.start()
    monkeypatch.setenv("APP_SSRF_ALLOW_HOSTS", f"127.0.0.1:{port}")
    get_settings.cache_clear()
    yield port, handler
    ctl.stop()
    get_settings.cache_clear()
