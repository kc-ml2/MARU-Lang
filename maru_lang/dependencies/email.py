"""Email service implementations constructed by the application context."""
from __future__ import annotations

from abc import ABC, abstractmethod
import smtplib
from email.mime.text import MIMEText
from pathlib import Path

from maru_lang.dependencies.email_templates import get_template
from maru_lang.settings import Settings


class EmailService(ABC):
    @abstractmethod
    def send_email(self, recipient: str, subject: str, body: str) -> bool: ...

    @abstractmethod
    def send_otp(self, recipient: str, code: str) -> bool: ...

    @abstractmethod
    def send_invitation(
        self, recipient: str, team_name: str, inviter_name: str
    ) -> bool: ...

    @abstractmethod
    def send_notification(
        self, recipient: str, team_name: str, inviter_name: str
    ) -> bool: ...


class SMTPEmailManager(EmailService):
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
        self.template_dir = str(template_dir) if template_dir else None

    def send_email(self, recipient: str, subject: str, body: str) -> bool:
        try:
            message = MIMEText(body, "plain")
            message["From"] = self.username
            message["To"] = recipient
            message["Subject"] = subject
            with smtplib.SMTP(self.host, self.port) as server:
                server.starttls()
                server.login(self.username, self.password)
                server.sendmail(self.username, recipient, message.as_string())
            return True
        except Exception:
            return False

    def send_otp(self, recipient: str, code: str) -> bool:
        subject, body = get_template("otp", self.template_dir)
        return self.send_email(
            recipient, subject.format(code=code), body.format(code=code)
        )

    def send_invitation(
        self, recipient: str, team_name: str, inviter_name: str
    ) -> bool:
        subject, body = get_template("invitation", self.template_dir)
        fields = {"team_name": team_name, "inviter_name": inviter_name}
        return self.send_email(
            recipient, subject.format(**fields), body.format(**fields)
        )

    def send_notification(
        self, recipient: str, team_name: str, inviter_name: str
    ) -> bool:
        subject, body = get_template("notification", self.template_dir)
        fields = {"team_name": team_name, "inviter_name": inviter_name}
        return self.send_email(
            recipient, subject.format(**fields), body.format(**fields)
        )


def create_email_service(settings: Settings) -> EmailService | None:
    if not all(
        [settings.smtp_host, settings.smtp_username, settings.smtp_password]
    ):
        return None
    return SMTPEmailManager(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        template_dir=settings.email_template_dir,
    )


__all__ = ["EmailService", "SMTPEmailManager", "create_email_service"]
