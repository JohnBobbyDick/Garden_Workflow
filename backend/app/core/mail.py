from __future__ import annotations

import socket
from email.message import EmailMessage

import aiosmtplib

from app.config import get_settings
from app.core.ssrf import check_url


async def send_mail(message: EmailMessage, *, host: str, port: int, security: str,
                    username: str | None = None, password: str | None = None) -> None:
    check_url(f"http://{host}:{port}/", get_settings().ssrf_allowed())
    refused, _ = await aiosmtplib.send(message, hostname=host, port=port, use_tls=security == "tls",
                                       start_tls=security == "starttls", username=username or None,
                                       password=password or None, timeout=30, local_hostname=socket.gethostname())
    if refused:
        raise RuntimeError("SMTP-сервер отклонил часть получателей")
