"""Application settings, read from environment variables prefixed with ``APP_`` (see ``.env.example``)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")

    env: str = "dev"
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'aisw.db').as_posix()}"
    data_dir: Path = BACKEND_DIR / "data"
    # base64 32 bytes; several keys for rotation: "1:<b64>,2:<b64>" (the highest version encrypts)
    master_key: str = ""
    jwt_secret: str = ""
    access_token_minutes: int = 15
    refresh_token_days: int = 14
    cors_origins: str = "http://localhost:5173,http://localhost:8080"
    public_url: str = "http://localhost:8080"
    scan_roots: str = str(REPO_ROOT / "fixtures")
    upload_retention_hours: int = 72
    upload_max_bytes: int = 50 * 1024 * 1024
    upload_max_files: int = 20_000
    upload_max_unpacked_bytes: int = 300 * 1024 * 1024
    inprocess_worker: bool = False
    ssrf_allow_hosts: str = ""
    telegram_api_base: str = "https://api.telegram.org"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_security: Literal["starttls", "tls", "none"] = "starttls"
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    node_timeout_seconds: float = 300.0
    run_timeout_seconds: float = 1800.0
    worker_poll_seconds: float = 1.0
    default_allowlist: str = "https://github.com/TBagirov/training"
    login_rate_limit: int = 10  # attempts per minute per (ip, email)
    max_body_bytes: int = 60 * 1024 * 1024

    def scan_root_paths(self) -> list[Path]:
        return [Path(p).resolve() for p in self.scan_roots.split(",") if p.strip()]

    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def ssrf_allowed(self) -> set[str]:
        return {h.strip().lower() for h in self.ssrf_allow_hosts.split(",") if h.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
