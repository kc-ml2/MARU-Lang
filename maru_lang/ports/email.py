"""Email delivery port used by application services."""
from typing import Protocol


class EmailService(Protocol):
    async def send_api_token(
        self, recipient: str, token: str, endpoint: str, expires_at: str
    ) -> bool: ...

    async def send_notification(
        self, recipient: str, team_name: str, inviter_name: str
    ) -> bool: ...
