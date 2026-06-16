"""
Email service dependency for FastAPI
"""
from abc import ABC, abstractmethod
from typing import Optional
from maru_lang.configs import get_config

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

    def send_invitation(self, recipient: str, team_name: str, inviter_name: str) -> bool:
        subject = f"Maru Lang - {team_name} 팀 초대"
        body = (
            f"{inviter_name}님이 {team_name} 팀에 초대했습니다.\n\n"
            f"Maru Lang에 가입하여 팀에 참여하세요.\n"
            f"가입 후 자동으로 팀에 소속됩니다."
        )
        return self.send_email(recipient, subject, body)

    def send_notification(self, recipient: str, team_name: str, inviter_name: str) -> bool:
        subject = f"Maru Lang - {team_name} 팀에 추가되었습니다"
        body = (
            f"{inviter_name}님이 {team_name} 팀에 추가했습니다.\n\n"
            f"로그인하여 팀을 확인하세요."
        )
        return self.send_email(recipient, subject, body)


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
