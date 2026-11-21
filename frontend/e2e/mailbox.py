"""Deliver browser-test mail to a private, per-run directory."""
import hashlib
import sys
from email import message_from_bytes
from email.policy import default
from pathlib import Path
from threading import Event

from aiosmtpd.controller import Controller


class Inbox:
    async def handle_DATA(self, server, session, envelope):  # noqa: N802 - SMTP callback
        body = message_from_bytes(envelope.content, policy=default).get_body().get_content()
        for recipient in envelope.rcpt_tos:
            name = hashlib.sha256(recipient.encode()).hexdigest()
            Path(sys.argv[1], name).write_text(body, encoding="utf-8")
        return "250 OK"


if __name__ == "__main__":
    smtp = Controller(Inbox(), hostname="127.0.0.1", port=int(sys.argv[2]), server_hostname="localhost")
    smtp.start()
    try:
        Event().wait()
    finally:
        smtp.stop()
