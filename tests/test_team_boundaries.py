"""Unit coverage for team boundary guards without a running database."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from maru_lang.services.authorization import require_team_member
from maru_lang.services.team import invite_member, remove_member


class TeamBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_personal_membership_does_not_grant_access(self):
        with patch('maru_lang.services.authorization.TeamMember.get_or_none',
                   new=AsyncMock(return_value=SimpleNamespace(role='admin'))), \
             patch('maru_lang.services.authorization.Team.get',
                   new=AsyncMock(return_value=SimpleNamespace(is_personal=True, manager_id=1))):
            with self.assertRaises(PermissionError):
                await require_team_member(10, SimpleNamespace(id=2))
            self.assertIsNotNone(await require_team_member(10, SimpleNamespace(id=1)))

    async def test_personal_team_rejects_invites(self):
        with patch('maru_lang.services.team.require_team_admin', new=AsyncMock()), \
             patch('maru_lang.services.team.Team.get',
                   new=AsyncMock(return_value=SimpleNamespace(is_personal=True))), \
             patch('maru_lang.services.team.TeamMember.create', new=AsyncMock()) as create:
            with self.assertRaises(PermissionError):
                await invite_member(10, 'user@example.com', SimpleNamespace(id=1),
                                    settings=SimpleNamespace(is_domain_allowed=lambda _: True))
            create.assert_not_awaited()

    async def test_owner_cannot_be_removed_by_another_admin(self):
        with patch('maru_lang.services.team.require_team_admin', new=AsyncMock()), \
             patch('maru_lang.services.team.Team.get',
                   new=AsyncMock(return_value=SimpleNamespace(manager_id=1))), \
             patch('maru_lang.services.team.TeamMember.get_or_none', new=AsyncMock()) as lookup:
            with self.assertRaises(PermissionError):
                await remove_member(10, 1, SimpleNamespace(id=2))
            lookup.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
