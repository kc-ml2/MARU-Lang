"""
Email service dependency for FastAPI
"""
from abc import ABC, abstractmethod
from typing import Optional
from fastapi import Depends
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
        self.sender_email = config.email.sender_email
        self.host = config.email.smtp.host
        self.port = config.email.smtp.port
        self.username = config.email.smtp.username
        self.password = config.email.smtp.password

    def send_email(self, recipient: str, subject: str, body: str) -> bool:
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart

            message = MIMEMultipart("alternative")
            message["From"] = self.sender_email
            message["To"] = recipient
            message["Subject"] = subject
            message.attach(MIMEText(body, "html"))

            with smtplib.SMTP(self.host, self.port) as server:
                server.starttls()
                server.login(self.username, self.password)
                server.sendmail(self.sender_email, recipient, message.as_string())
            return True
        except Exception as e:
            print(f"Failed to send email via SMTP: {e}")
            return False

    def send_otp(self, recipient: str, code: str) -> bool:
        subject = f"{code} - Maru Lang Verification Code"
        body = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; text-align: center; padding: 40px; background-color: #f9f9f9;">
            <div style="background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); max-width: 400px; margin: auto;">
                <h2 style="color: #333; font-weight: 600;">Your Verification Code</h2>
                <p style="color: #666; font-size: 16px;">Use this code to verify your email address:</p>
                <div style="font-size: 28px; font-weight: bold; color: #007AFF; letter-spacing: 4px; padding: 12px 20px; border-radius: 8px; background: #f2f2f7; display: inline-block; margin: 20px 0;">
                    {code}
                </div>
                <p style="color: #999; font-size: 14px;">This code expires in 10 minutes.</p>
            </div>
        </div>
        """
        return self.send_email(recipient, subject, body)


class O365EmailManager(EmailService):
    """Office 365 email service implementation"""

    def __init__(self):
        self.sender_email = config.email.sender_email
        self.client_id = config.email.o365.client_id
        self.client_secret = config.email.o365.client_secret
        self.tenant_id = config.email.o365.tenant_id

    def send_email(self, recipient: str, subject: str, body: str) -> bool:
        try:
            from O365 import Account

            credentials = (self.client_id, self.client_secret)
            scopes = ["https://graph.microsoft.com/.default"]
            account = Account(
                credentials,
                auth_flow_type="credentials",
                tenant_id=self.tenant_id
            )

            if not account.is_authenticated:
                account.authenticate(scopes=scopes)

            mailbox = account.mailbox(resource=self.sender_email)
            message = mailbox.new_message()
            message.to.add(recipient)
            message.subject = subject
            message.body = body
            message.body_type = "HTML"
            message.send()
            return True
        except Exception as e:
            print(f"Failed to send email: {e}")
            return False

    def send_otp(self, recipient: str, code: str) -> bool:
        subject = f"{code} - Maru Lang Verification Code"
        body = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; text-align: center; padding: 40px; background-color: #f9f9f9;">
            <div style="background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); max-width: 400px; margin: auto;">
                <h2 style="color: #333; font-weight: 600;">Your Verification Code</h2>
                <p style="color: #666; font-size: 16px;">Use this code to verify your email address:</p>
                <div style="font-size: 28px; font-weight: bold; color: #007AFF; letter-spacing: 4px; padding: 12px 20px; border-radius: 8px; background: #f2f2f7; display: inline-block; margin: 20px 0;">
                    {code}
                </div>
                <p style="color: #999; font-size: 14px;">This code expires in 10 minutes.</p>
            </div>
        </div>
        """
        return self.send_email(recipient, subject, body)


def get_email_manager() -> Optional[EmailService]:
    """Get email service instance based on settings"""
    if not config.email.service_type:
        return None

    if config.email.service_type == "o365":
        if all([config.email.o365.client_id, config.email.o365.client_secret, config.email.o365.tenant_id, config.email.sender_email]):
            try:
                return O365EmailManager()
            except Exception as e:
                print(f"Failed to initialize O365 Email Manager: {e}")
                return None

    if config.email.service_type == "smtp":
        if all([config.email.smtp.host, config.email.smtp.username, config.email.smtp.password, config.email.sender_email]):
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
    "O365EmailManager",
    "SMTPEmailManager",
    "get_email_manager",
    "get_email_service_dependency",
]
