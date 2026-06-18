"""
Email service dependency for FastAPI
"""
from abc import ABC, abstractmethod
from typing import Optional
from maru_lang.configs import get_config
from maru_lang.dependencies.email_templates import get_template

config = get_config()


class EmailService(ABC):
    """Abstract base class for email services"""

    @abstractmethod
    def send_email(self, recipient: str, subject: str, body: str) -> bool:
        pass

    @abstractmethod
    def send_otp(self, recipient: str, code: str) -> bool:
        pass

    @abstractmethod
    def send_invitation(self, recipient: str, team_name: str, inviter_name: str) -> bool:
        pass

    @abstractmethod
    def send_notification(self, recipient:
         str, team_name: str, inviter_name: str) -> bool:
        pass


class SMTPEmailManager(EmailService):
    """SMTP email service implementation"""

    def __init__(self):
        self.host = config.smtp.host
        self.port = config.smtp.port
        self.username = config.smtp.username
        self.password = config.smtp.password
        self.template_dir = config.email_template_dir

    def send_email(self, recipient: str, subject: str, body: str) -> bool:
        try:
            import smtplib
            from email.mime.text import MIMEText

            message = MIMEText(body, "plain")
            message["From"] = self.username
            message["To"] = recipient
            message["Subject"] = subject

            with smtplib.SMTP(self.host, self.port) as server:
                server.starttls()
                server.login(self.username, self.password)
                server.sendmail(self.username, recipient, message.as_string())
            return True
        except Exception as e:
            print(f"Failed to send email via SMTP: {e}")
            return False

    def send_otp(self, recipient: str, code: str) -> bool:
        subject, body = get_template("otp", self.template_dir)
        return self.send_email(recipient, subject.format(code=code), body.format(code=code))

    def send_invitation(self, recipient: str, team_name: str, inviter_name: str) -> bool:
        subject, body = get_template("invitation", self.template_dir)
        fields = {"team_name": team_name, "inviter_name": inviter_name}
        return self.send_email(recipient, subject.format(**fields), body.format(**fields))

    def send_notification(self, recipient: str, team_name: str, inviter_name: str) -> bool:
        subject, body = get_template("notification", self.template_dir)
        fields = {"team_name": team_name, "inviter_name": inviter_name}
        return self.send_email(recipient, subject.format(**fields), body.format(**fields))


def get_email_manager() -> Optional[EmailService]:
    """Get email service instance based on settings"""
    smtp = config.smtp
    if all([smtp.host, smtp.username, smtp.password]):
        try:
            return SMTPEmailManager()
        except Exception as e:
            print(f"Failed to initialize SMTP Email Manager: {e}")
            return None
    return None


def get_email_service_dependency() -> Optional[EmailService]:
    """FastAPI dependency for email service"""
    return get_email_manager()


__all__ = [
    "EmailService",
    "SMTPEmailManager",
    "get_email_manager",
    "get_email_service_dependency",
]
