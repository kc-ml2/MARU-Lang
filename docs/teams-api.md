# Teams API

## Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `GET` | `/teams` | List teams the current user belongs to | Login required |
| `GET` | `/teams/{team_id}` | Get team detail (members + folders) | Team member |
| `POST` | `/teams` | Create a new team (creator becomes admin) | Login required |
| `POST` | `/teams/{team_id}/members` | Invite a member by email | Admin only |
| `DELETE` | `/teams/{team_id}/members/{user_id}` | Remove a member from team | Admin only |

## Response Schema

### List Teams (`GET /teams`)

```json
[{ "id": 1, "name": "TeamName", "role": "admin" }]
```

### Team Detail (`GET /teams/{id}`)

```json
{
  "id": 1,
  "name": "TeamName",
  "members": [
    { "id": 1, "email": "user@example.com", "name": "John Doe", "role": "admin" }
  ],
  "folders": [
    { "id": 1, "name": "FolderName", "document_count": 5 }
  ]
}
```

### Create Team (`POST /teams`)

- Request: `{ "name": "NewTeam" }`
- Response (201): `{ "id": 1, "name": "NewTeam", "role": "admin" }`

### Invite Member (`POST /teams/{id}/members`)

- Request: `{ "email": "user@example.com", "name": "John Doe" }`
- Response (201): `{ "id": 2, "email": "user@example.com", "name": "John Doe", "role": "member" }`

**동작:**
- **기존 유저**: 팀에 추가 + notification 이메일 전송
- **미가입 유저**: `anonymous` 롤의 유저 자동 생성 → 팀에 추가 + invitation 이메일 전송. 해당 유저가 나중에 로그인하면 자동으로 팀에 소속되어 보인다.

### Remove Member (`DELETE /teams/{id}/members/{user_id}`)

- Response: `204 No Content`

## Business Rules

- Member responses always include **email address** (frontend can display email when name is not set)
- Duplicate team name on creation → `409 Conflict`
- Inviting an unregistered email → anonymous 유저 생성 후 팀에 추가 (201)
- Inviting an existing member → `400 Bad Request`
- Non-member accessing team detail → `403 Forbidden`
- Non-admin attempting invite/remove → `403 Forbidden`
- Admin cannot remove themselves → `403 Forbidden`
- Last admin cannot be removed → `403 Forbidden`

## Tests

18 integration tests passing

```bash
pytest tests/api/test_teams.py -v
```

| Test | Description |
|------|-------------|
| `test_returns_teams_with_role` | Returns team name and user's role |
| `test_empty_when_no_membership` | Empty list for user with no teams |
| `test_unauthorized_without_token` | 401 without auth token |
| `test_returns_members_and_folders` | Detail includes members and folders |
| `test_non_member_gets_403` | Non-member blocked from detail |
| `test_create_team_success` | Team created with admin membership |
| `test_duplicate_name_returns_409` | Duplicate name prevented |
| `test_admin_invites_existing_member` | Admin invites existing member successfully |
| `test_invite_unregistered_email_creates_anonymous_user` | Unregistered email creates anonymous user and adds to team |
| `test_invite_sends_invitation_email_for_new_user` | Invitation email sent for unregistered user |
| `test_invite_sends_notification_email_for_existing_user` | Notification email sent for existing user |
| `test_non_admin_cannot_invite` | Member role cannot invite |
| `test_invite_already_member_returns_400` | Duplicate invite rejected |
| `test_admin_removes_member` | Admin removes member + DB verified |
| `test_cannot_remove_self` | Self-removal blocked |
| `test_non_admin_cannot_remove` | Member role cannot remove |
| `test_last_admin_cannot_be_removed` | Can remove admin when 2+ admins exist |
| `test_remove_nonexistent_member_returns_400` | Non-existent member returns 400 |
