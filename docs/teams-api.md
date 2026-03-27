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

### Remove Member (`DELETE /teams/{id}/members/{user_id}`)

- Response: `204 No Content`

## Business Rules

- Member responses always include **email address** (frontend can display email when name is not set)
- Duplicate team name on creation → `409 Conflict`
- Inviting an unregistered email → `400 Bad Request`
- Inviting an existing member → `400 Bad Request`
- Non-member accessing team detail → `403 Forbidden`
- Non-admin attempting invite/remove → `403 Forbidden`
- Admin cannot remove themselves → `403 Forbidden`
- Last admin cannot be removed → `403 Forbidden`

## Tests

16 integration tests passing

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
| `test_admin_invites_member` | Admin invites member successfully |
| `test_non_admin_cannot_invite` | Member role cannot invite |
| `test_invite_nonexistent_user_returns_400` | Unregistered email rejected |
| `test_invite_already_member_returns_400` | Duplicate invite rejected |
| `test_admin_removes_member` | Admin removes member + DB verified |
| `test_cannot_remove_self` | Self-removal blocked |
| `test_non_admin_cannot_remove` | Member role cannot remove |
| `test_last_admin_cannot_be_removed` | Can remove admin when 2+ admins exist |
| `test_remove_nonexistent_member_returns_400` | Non-existent member returns 400 |
