"""Email delivery port used by application services."""
from typing import Protocol


class EmailService(Protocol):
    async def send_otp(self, recipient: str, code: str) -> bool: ...

    async def send_notification(
        self, recipient: str, team_name: str, inviter_name: str
    ) -> bool: ...
