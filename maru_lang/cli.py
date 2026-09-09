"""Local system administration, authorized by access to server configuration."""
import argparse
import asyncio
import getpass
import json
from pathlib import Path

from maru_lang.core.relation_db.connection import database_context
from maru_lang.core.relation_db.models.auth import ApiToken, Team, User
from maru_lang.adapters.smtp_email import create_email_service
from maru_lang.services.api_tokens import issue_token, parse_expiry, revoke_token
from maru_lang.services.operator_users import add_user, normalized_email
from maru_lang.core.relation_db.models.documents import SourceStorage, TeamStorageLink
from maru_lang.services.system_admin import (
    register_external, share_external, unshare_external, unregister_external,
)
from maru_lang.settings import Settings


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(prog='maru')
    cli.add_argument('--config', type=Path, help='YAML config path (or MARU_CONFIG)')
    entries = cli.add_subparsers(dest='entry', required=True)
    add = entries.add_parser('add', help='Register a user and add them to a team')
    add.add_argument('email')
    add.add_argument('-t', '--team', required=True)
    add.add_argument('-r', '--role', choices=['admin', 'member'], default='member')
    add.add_argument('--issue-token', action='store_true', help='Also issue when already a member')
    add.add_argument('--expires-in', type=parse_expiry, help='Optional token lifetime, e.g. 90d')
    tokens = entries.add_parser('token', help='Manage operator-issued API tokens')
    token_commands = tokens.add_subparsers(dest='command', required=True)
    issue = token_commands.add_parser('issue')
    issue.add_argument('email')
    issue.add_argument('--expires-in', type=parse_expiry)
    listing = token_commands.add_parser('list')
    listing.add_argument('email')
    revoke = token_commands.add_parser('revoke')
    revoke.add_argument('token_id', type=int)
    admin = entries.add_parser('admin')
    commands = admin.add_subparsers(dest='command', required=True)
    commands.add_parser('list-teams')
    commands.add_parser('list-storages')
    register = commands.add_parser('register-external')
    register.add_argument('--path', type=Path, required=True)
    register.add_argument('--name', required=True)
    for name in ('share', 'unshare', 'unregister-external'):
        command = commands.add_parser(name)
        command.add_argument('--storage-id', required=True)
        if name != 'unregister-external':
            command.add_argument('--team-id', type=int, required=True)
    return cli


async def run(args) -> object:
    settings = Settings.from_env(args.config)
    # CLI does not run application startup provisioning or start MCP.
    async with database_context(settings.database_url):
        if args.entry == 'add':
            user, result = await add_user(settings, args.email, args.team, args.role)
            if result['member_created'] or args.issue_token:
                result.update(await deliver_token(settings, user, args.expires_in))
            else:
                result['token_status'] = 'unchanged; use maru token issue to issue another token'
            return result
        if args.entry == 'token':
            if args.command == 'revoke':
                await revoke_token(args.token_id)
                return {'token_id': args.token_id, 'status': 'revoked'}
            email = normalized_email(args.email, settings)
            user = await User.get_or_none(email=email)
            if user is None:
                raise ValueError('User not found; register with maru add first')
            if args.command == 'issue':
                return await deliver_token(settings, user, args.expires_in)
            return await ApiToken.filter(user=user).order_by('id').values(
                'id', 'created_at', 'expires_at', 'revoked_at'
            )
        if args.command == 'list-teams':
            return await Team.all().order_by('id').values('id', 'name', 'is_personal')
        if args.command == 'list-storages':
            storages = []
            for storage in await SourceStorage.all().order_by('id'):
                storages.append({
                    'id': storage.id, 'name': storage.name,
                    'storage_type': storage.storage_type, 'owner_type': storage.owner_type,
                    'external_path': storage.external_path,
                    'team_ids': await TeamStorageLink.filter(storage_id=storage.id)
                        .order_by('team_id').values_list('team_id', flat=True),
                })
            return storages
        if args.command == 'register-external':
            storage = await register_external(settings.filesystem_root, args.path, args.name)
            return {'storage_id': storage.id, 'external_path': storage.external_path}
        if args.command == 'share':
            await share_external(args.storage_id, args.team_id)
        elif args.command == 'unshare':
            await unshare_external(args.storage_id, args.team_id)
        else:
            await unregister_external(args.storage_id)
        return {'storage_id': args.storage_id, 'status': 'ok'}


async def deliver_token(settings: Settings, user: User, duration) -> dict:
    record, token = await issue_token(user, duration)
    # Flush the only plaintext console output before attempting network delivery.
    print(json.dumps({
        'event': 'token_issued', 'email': user.email, 'token_id': record.id,
        'mcp_url': f'{settings.public_url}/mcp', 'token': token,
        'expires_at': record.expires_at,
        'warning': 'Secret credential: do not save this output in shared logs',
    }, default=str), flush=True)
    service = create_email_service(settings)
    sent = False
    if service is not None:
        try:
            sent = await service.send_api_token(
                user.email, token, f'{settings.public_url}/mcp',
                record.expires_at.isoformat() if record.expires_at else 'never',
            )
        except Exception:
            # Do not echo exception text that could contain the credential.
            sent = False
    return {
        'token_id': record.id,
        'email_status': 'sent' if sent else 'failed' if service else 'not_configured',
        'registration_status': 'completed',
    }


def main() -> None:
    args = parser().parse_args()
    try:
        result = asyncio.run(run(args))
    except (ValueError, OSError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps({'operator': getpass.getuser(),
                      'operation': args.entry if args.entry == 'add' else args.command,
                      'result': result}, ensure_ascii=False, default=str))
    if isinstance(result, dict) and result.get('email_status') in {'failed', 'not_configured'}:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
