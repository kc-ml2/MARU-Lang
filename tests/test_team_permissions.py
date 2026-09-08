"""Team permission discovery is scoped and informational."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from maru_lang.enums import TeamRole
from maru_lang.services.team import get_team_permissions


class PermissionTests(unittest.IsolatedAsyncioTestCase):
    async def permissions(self, role, personal=False):
        with patch('maru_lang.services.team.require_team_member',
                   new=AsyncMock(return_value=SimpleNamespace(role=role))), \
             patch('maru_lang.services.team.Team.get', new=AsyncMock(return_value=
                   SimpleNamespace(id=10, manager_id=1, is_personal=personal))):
            return await get_team_permissions(10, SimpleNamespace(id=1))

    async def test_owner_does_not_bypass_role(self):
        result = await self.permissions(TeamRole.MEMBER)
        self.assertTrue(result['is_owner'])
        self.assertFalse(result['permissions']['add_members'])
        self.assertFalse(result['permissions']['create_storage'])

    async def test_collaboration_admin(self):
        result = await self.permissions(TeamRole.ADMIN)
        self.assertTrue(result['permissions']['add_members'])
        self.assertTrue(result['permissions']['request_team_deletion'])

    async def test_personal_admin(self):
        result = await self.permissions(TeamRole.ADMIN, personal=True)
        self.assertFalse(result['permissions']['add_members'])
        self.assertFalse(result['permissions']['request_team_deletion'])
        self.assertTrue(result['permissions']['create_storage'])

    async def test_nonmember_denied_before_discovery(self):
        with patch('maru_lang.services.team.require_team_member',
                   new=AsyncMock(side_effect=PermissionError)), \
             patch('maru_lang.services.team.Team.get', new=AsyncMock()) as lookup:
            with self.assertRaises(PermissionError):
                await get_team_permissions(10, SimpleNamespace(id=2))
            lookup.assert_not_awaited()
