"""
Email service dependency for FastAPI
"""
from abc import ABC, abstractmethod
from typing import Optional
from maru_lang.configs.system_config import get_system_config

config = get_system_config()


class EmailService(ABC):
    """Abstract base class for email services"""

    @abstractmethod
    def send_email(self, recipient: str, subject: str, body: str) -> bool:
        pass

    @abstractmethod
    def send_otp(self, recipient: str, code: str) -> bool:
        pass


class SMTPEmailManager(EmailService):
    """SMTP email service implementation"""

    def __init__(self):
        self.host = config.email.smtp.host
        self.port = config.email.smtp.port
        self.username = config.email.smtp.username
        self.password = config.email.smtp.password

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
        subject = f"{code} - Maru Lang Code"
        body = f"Your verification code is: {code}\n\nThis code expires in 5 minutes."
        return self.send_email(recipient, subject, body)


def get_email_manager() -> Optional[EmailService]:
    """Get email service instance based on settings"""
    smtp = config.email.smtp
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
