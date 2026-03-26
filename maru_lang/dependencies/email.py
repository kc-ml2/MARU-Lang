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

    def send_email(self, recipient: str, subject: str, body_html: str, body_text: str = "") -> bool:
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart

            message = MIMEMultipart("alternative")
            message["From"] = self.username
            message["To"] = recipient
            message["Subject"] = subject

            if body_text:
                message.attach(MIMEText(body_text, "plain"))
            message.attach(MIMEText(body_html, "html"))

            with smtplib.SMTP(self.host, self.port) as server:
                server.starttls()
                server.login(self.username, self.password)
                server.sendmail(self.username, recipient, message.as_string())
            return True
        except Exception as e:
            print(f"Failed to send email via SMTP: {e}")
            return False

    def send_otp(self, recipient: str, code: str) -> bool:
        subject = f"{code} - Maru Lang Verification Code"
        body_text = f"Your verification code is: {code}\n\nThis code expires in 5 minutes."
        body_html = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; text-align: center; padding: 40px; background-color: #f9f9f9;">
            <div style="background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); max-width: 400px; margin: auto;">
                <h2 style="color: #333; font-weight: 600;">Your Verification Code</h2>
                <p style="color: #666; font-size: 16px;">Use this code to verify your email address:</p>
                <div style="font-size: 28px; font-weight: bold; color: #007AFF; letter-spacing: 4px; padding: 12px 20px; border-radius: 8px; background: #f2f2f7; display: inline-block; margin: 20px 0;">
                    {code}
                </div>
                <p style="color: #999; font-size: 14px;">This code expires in 5 minutes.</p>
            </div>
        </div>
        """
        return self.send_email(recipient, subject, body_html, body_text)


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
