"""The service binary is also its own operations CLI: serve, migrate,
bootstrap, add-member, and openapi are subcommands of one entry point. Each one boots
the same way before it does anything else."""

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

import uvicorn

from tadas.infra.impl.local import InfraLocalImpl
from tadas.om.exceptions import Conflict
from tadas.om.opcontext import AppContext, AppType, Role
from tadas.om.storage import migrate
from tadas.om.storage.impl.memory import StorageMemoryImpl
from tadas.services.api.app import create_app
from tadas.services.api.container import AppContainer, boot
from tadas.services.api.settings import ApiSettings


def serve(args: argparse.Namespace) -> int:
    settings = ApiSettings()
    boot(settings)
    uvicorn.run(
        "tadas.services.api.app:create_app",
        factory=True,
        host=args.host or settings.host,
        port=args.port or settings.port,
        log_config=None,
    )
    return 0


def migrate_roles(args: argparse.Namespace) -> int:
    boot(ApiSettings())
    forwarded = (
        ["upgrade"] + (["--all"] if args.all else []) + (["--role", args.role] if args.role else [])
    )
    return migrate.main(forwarded)


def bootstrap(args: argparse.Namespace) -> int:
    async def run() -> int:
        settings = ApiSettings()
        boot(settings)
        container = AppContainer.build(settings)
        await container.start()
        try:
            ctx, org = await container.managers.tenancy.bootstrap(
                args.org,
                args.slug,
                args.email,
                args.password,
                args.name,
                operator=args.operator,
                app=AppContext(type=AppType.CLI, version=f"cli@{settings.version}"),
            )
        except Conflict:
            # The only conflict bootstrap raises is a taken slug.
            if not args.if_absent:
                raise
            print(f"org {args.slug} already exists; nothing to do")
            return 0
        finally:
            await container.close()
        print(f"bootstrapped org {org.slug} ({org.id}) with owner {ctx.user_id}")
        return 0

    return asyncio.run(run())


def add_member(args: argparse.Namespace) -> int:
    async def run() -> int:
        settings = ApiSettings()
        boot(settings)
        container = AppContainer.build(settings)
        await container.start()
        try:
            user, created = await container.managers.tenancy.add_member(
                args.slug, args.email, args.password, args.name, Role(args.role)
            )
        finally:
            await container.close()
        if created:
            print(f"added {user.email} to org {args.slug} as {args.role}")
        else:
            print(f"{user.email} is already a member of org {args.slug}; nothing to do")
        return 0

    return asyncio.run(run())


def openapi(args: argparse.Namespace) -> int:
    settings = ApiSettings.model_validate({"environment": "test"})
    boot(settings)
    with tempfile.TemporaryDirectory() as tmp:
        container = AppContainer.for_tests(StorageMemoryImpl(), InfraLocalImpl(Path(tmp)), settings)
        document = create_app(container).openapi()
    text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if args.out == "-":
        sys.stdout.write(text)
    else:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        print(f"wrote {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tadas-api")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="run the API process")
    p_serve.add_argument("--host")
    p_serve.add_argument("--port", type=int)

    p_migrate = sub.add_parser("migrate", help="apply migrations (--all, or --role <role>)")
    p_migrate.add_argument("--role")
    p_migrate.add_argument("--all", action="store_true")

    p_boot = sub.add_parser("bootstrap", help="seed a fresh environment with one org and its owner")
    p_boot.add_argument("--org", required=True)
    p_boot.add_argument("--slug", required=True)
    p_boot.add_argument("--email", required=True)
    p_boot.add_argument("--password", required=True)
    p_boot.add_argument("--name", required=True)
    p_boot.add_argument("--operator", action="store_true")
    p_boot.add_argument(
        "--if-absent", action="store_true", help="succeed without changes when the slug exists"
    )

    p_member = sub.add_parser(
        "add-member", help="seed a person into an existing org; a no-op for a member"
    )
    p_member.add_argument("--slug", required=True, help="the org to join")
    p_member.add_argument("--email", required=True)
    p_member.add_argument("--password", required=True, help="kept only for a new identity")
    p_member.add_argument("--name", required=True)
    p_member.add_argument(
        "--role", default="member", choices=[r.value for r in Role if r is not Role.OWNER]
    )

    p_openapi = sub.add_parser("openapi", help="emit the OpenAPI document")
    p_openapi.add_argument("--out", default="-")

    args = parser.parse_args(argv)
    if args.command == "serve":
        return serve(args)
    if args.command == "migrate":
        return migrate_roles(args)
    if args.command == "bootstrap":
        return bootstrap(args)
    if args.command == "add-member":
        return add_member(args)
    return openapi(args)


if __name__ == "__main__":
    sys.exit(main())
