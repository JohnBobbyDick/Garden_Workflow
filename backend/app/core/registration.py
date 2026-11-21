"""Short-lived email challenges. Successful consumption and account creation share one transaction."""

import hmac
import secrets
from datetime import timedelta
from email.message import EmailMessage

from sqlalchemy import delete, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.errors import ApiError
from app.core.mail import send_mail
from app.core.security import jwt_secret
from app.models import RegistrationCode, utcnow

LIFETIME = timedelta(minutes=10)
RESEND_DELAY = timedelta(minutes=1)
MAX_ATTEMPTS = 5


def _digest(email: str, code: str) -> str:
    return hmac.digest(jwt_secret().encode(), f"registration:{email}:{code}".encode(), "sha256").hex()


async def send_registration_code(s: Session, email: str, locale: str) -> None:
    settings = get_settings()
    if not settings.smtp_host or not settings.smtp_from:
        raise ApiError(503, "mail_not_configured", "отправитель писем регистрации не настроен")
    now = utcnow()
    code = f"{secrets.randbelow(1_000_000):06d}"
    digest = _digest(email, code)
    row = RegistrationCode
    s.execute(delete(row).where(or_(row.issued_at <= now - LIFETIME,
                                    (row.email == email) & (row.issued_at <= now - RESEND_DELAY))))
    s.add(row(email=email, digest=digest, issued_at=now, attempts_left=MAX_ATTEMPTS))
    try:
        s.commit()
    except IntegrityError:
        s.rollback()
        raise ApiError(429, "code_recently_sent", "повторная отправка доступна через минуту") from None

    try:
        msg = EmailMessage()
        msg["From"], msg["To"] = settings.smtp_from, email
        if locale == "en":
            msg["Subject"] = "AI Security Workflow — confirm your email"
            msg.set_content(f"Your registration code is {code}. It is valid for 10 minutes.")
        else:
            msg["Subject"] = "AI Security Workflow — подтверждение почты"
            msg.set_content(f"Ваш код регистрации — {code}. Он действует 10 минут.")
        await send_mail(msg, host=settings.smtp_host, port=settings.smtp_port, security=settings.smtp_security,
                        username=settings.smtp_username, password=settings.smtp_password)
    except Exception:
        s.execute(delete(row).where(row.email == email, row.digest == digest, row.issued_at == now))
        s.commit()
        raise ApiError(503, "mail_delivery_failed", "письмо не удалось отправить, попробуйте ещё раз") from None


def consume_registration_code(s: Session, email: str, code: str) -> None:
    row = RegistrationCode
    active = (row.email == email, row.issued_at > utcnow() - LIFETIME, row.attempts_left > 0)
    if s.execute(delete(row).where(*active, row.digest == _digest(email, code))).rowcount:
        return
    s.execute(update(row).where(*active).values(attempts_left=row.attempts_left - 1))
    s.commit()
    raise ApiError(400, "invalid_registration_code", "код неверен или истёк, проверьте письмо или запросите новый")
