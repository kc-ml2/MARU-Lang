import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from maru_lang.services.team import invite_member


class MemberAdditionTests(unittest.IsolatedAsyncioTestCase):
    async def test_nonadmin_cannot_add(self):
        with patch('maru_lang.services.team.require_team_admin',
                   new=AsyncMock(side_effect=PermissionError)), \
             patch('maru_lang.services.team.TeamMember.create', new=AsyncMock()) as create:
            with self.assertRaises(PermissionError):
                await invite_member(10, 'u@example.com', SimpleNamespace(id=1), settings=None)
            create.assert_not_awaited()

    async def test_notification_failure_does_not_report_addition_failure(self):
        user = SimpleNamespace(id=2, email='u@example.com', name='User')
        with patch('maru_lang.services.team.require_team_admin', new=AsyncMock()), \
             patch('maru_lang.services.team.Team.get', new=AsyncMock(
                 return_value=SimpleNamespace(is_personal=False, name='Team'))), \
             patch('maru_lang.services.team.User.get_or_none', new=AsyncMock(return_value=user)), \
             patch('maru_lang.services.team.TeamMember.create', new=AsyncMock(
                 return_value=SimpleNamespace(role='member'))) as create, \
             self.assertLogs('maru.audit', level='INFO') as logs:
            result = await invite_member(
                10, user.email, SimpleNamespace(id=1, name='Admin', email='admin@example.com'),
                settings=SimpleNamespace(is_domain_allowed=lambda _: True),
                email_service=SimpleNamespace(send_notification=AsyncMock(side_effect=RuntimeError)),
            )
            self.assertEqual(result['id'], 2)
            create.assert_awaited_once()
            self.assertEqual(logs.records[0].actor_user_id, 1)
            self.assertEqual(logs.records[0].target_user_id, 2)
