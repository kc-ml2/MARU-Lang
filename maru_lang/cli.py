"""Local system administration, authorized by access to server configuration."""
import argparse
import asyncio
import getpass
import json
from pathlib import Path

from maru_lang.core.relation_db.connection import database_context
from maru_lang.core.relation_db.models.auth import Team
from maru_lang.core.relation_db.models.documents import SourceStorage, TeamStorageLink
from maru_lang.services.system_admin import (
    register_external, share_external, unshare_external, unregister_external,
)
from maru_lang.settings import Settings


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(prog='maru')
    admin = cli.add_subparsers(dest='entry', required=True).add_parser('admin')
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
    settings = Settings.from_env()
    # CLI does not run application startup provisioning or start MCP.
    async with database_context(settings.database_url):
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


def main() -> None:
    args = parser().parse_args()
    try:
        result = asyncio.run(run(args))
    except (ValueError, OSError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps({'operator': getpass.getuser(), 'operation': args.command,
                      'result': result}, ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()
