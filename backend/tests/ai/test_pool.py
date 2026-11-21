"""LLM pool configuration (LLM_PROXY.md §2–3.1): list splitting, proxy entries, retry formula, environment."""

from app.ai.pool import NEMOTRON_LIGHTNING, LLMEnv, auto_retries, mask_proxy, parse_proxy, split_list


def test_split_list_separators_and_dupes():
    assert split_list("a, b;c  a ,") == ["a", "b", "c"]
    assert split_list(None) == [] and split_list("") == []


def test_parse_proxy_formats():
    # everything after the third colon is the password; login/password are percent-encoded
    assert parse_proxy("1.2.3.4:1080:user:p:a@ss#1", "socks5") == "socks5://user:p%3Aa%40ss%231@1.2.3.4:1080"
    assert parse_proxy("1.2.3.4:user:pw", "http", default_port="3128") == "http://user:pw@1.2.3.4:3128"
    assert parse_proxy("1.2.3.4:user:pw", "http") == "http://user:pw@1.2.3.4"
    assert parse_proxy("socks5://u:p@h:1", "http") == "socks5://u:p@h:1"
    assert parse_proxy("1.2.3.4:1080:u:p") == "auto://u:p@1.2.3.4:1080"
    assert parse_proxy("garbage") is None
    assert parse_proxy("  ") is None


def test_auto_retries_formula():
    assert auto_retries(1, []) == 3
    assert auto_retries(2, ["auto://a", "auto://b"]) == 4  # auto proxy = 2 candidates
    assert auto_retries(1, ["http://a", "http://b", "http://c", "http://d"]) == 4
    assert auto_retries(9, []) == 6


def test_env_models_and_keys(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "k1,k2,k1")
    monkeypatch.setenv("NVIDIA_MODEL", "unsupported")
    monkeypatch.setenv("NVIDIA_PROXIES", "1.2.3.4:1080:u:p; 5.6.7.8:3128:u:p")
    env = LLMEnv(_env_file=None)
    assert env.keys == ["k1", "k2"]
    assert env.models == [NEMOTRON_LIGHTNING]
    assert env.proxies == ["auto://u:p@1.2.3.4:1080", "auto://u:p@5.6.7.8:3128"]
    assert env.retries == 4
    assert env.enabled is False  # conftest disables the platform in every test session.


def test_env_defaults_to_nvidia_and_requires_key(monkeypatch):
    for k in ("LLM_PROVIDER", "LLM_ENABLED", "NVIDIA_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    env = LLMEnv(_env_file=None)
    assert env.enabled is True and env.provider == "nvidia" and not env.configured
    assert env.models == [NEMOTRON_LIGHTNING]
    assert env.ollama_url == "http://localhost:11434"


def test_mask_proxy_hides_credentials():
    assert mask_proxy("socks5://u:secret@h:1080") == "socks5://h:1080"
    assert mask_proxy("auto://u:secret@h") == "auto://h"


def test_legacy_proxy_names_feed_nvidia_rotation(monkeypatch):
    for name in ("GEMINI_PROXIES", "GEMENI_PROXIES"):
        with monkeypatch.context() as patch:
            patch.setenv("NVIDIA_PROXIES", "")
            patch.setenv(name, "a:8080:user:pass,b:8081:user:pass")
            env = LLMEnv(_env_file=None)
            assert env.proxies == ["auto://user:pass@a:8080", "auto://user:pass@b:8081"]
            assert env.retries == 4
            patch.setenv("NVIDIA_PROXIES", "preferred:8082:user:pass")
            assert LLMEnv(_env_file=None).proxies == ["auto://user:pass@preferred:8082"]
