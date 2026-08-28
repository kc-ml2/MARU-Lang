"""SMTP implementation of the email delivery port."""
from __future__ import annotations

import asyncio
import logging
import smtplib
from email.mime.text import MIMEText
from pathlib import Path

from maru_lang.adapters.email_templates import get_template
from maru_lang.ports.email import EmailService
from maru_lang.settings import Settings

logger = logging.getLogger(__name__)


class SMTPEmailService:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        template_dir: Path | None = None,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.template_dir = template_dir

    def _send(self, recipient: str, subject: str, body: str) -> bool:
        message = MIMEText(body, "plain", "utf-8")
        message["From"] = self.username
        message["To"] = recipient
        message["Subject"] = subject
        try:
            with smtplib.SMTP(self.host, self.port) as server:
                server.starttls()
                server.login(self.username, self.password)
                server.sendmail(self.username, recipient, message.as_string())
            return True
        except Exception:
            logger.exception("Failed to send email to %s", recipient)
            return False

    async def send_otp(self, recipient: str, code: str) -> bool:
        subject, body = get_template("otp", self.template_dir)
        return await asyncio.to_thread(
            self._send,
            recipient,
            subject.format(code=code),
            body.format(code=code),
        )

    async def send_notification(
        self, recipient: str, team_name: str, inviter_name: str
    ) -> bool:
        return await self._send_team_message(
            "notification", recipient, team_name, inviter_name
        )

    async def _send_team_message(
        self, name: str, recipient: str, team_name: str, inviter_name: str
    ) -> bool:
        subject, body = get_template(name, self.template_dir)
        fields = {"team_name": team_name, "inviter_name": inviter_name}
        return await asyncio.to_thread(
            self._send, recipient, subject.format(**fields), body.format(**fields)
        )


def create_email_service(settings: Settings) -> EmailService | None:
    if not all(
        [settings.smtp_host, settings.smtp_username, settings.smtp_password]
    ):
        return None
    return SMTPEmailService(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        template_dir=settings.email_template_dir,
    )
