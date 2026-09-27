"""运维命令:`uv run python -m community.cli <命令>`(容器里 `python -m community.cli <命令>`)。

    migrate          把数据库升到最新(alembic upgrade head)
    create-admin     建第一个管理员(或把已有账号提成管理员)
    set-role         改一个账号的角色(user / moderator / admin)
    seed-official    导入官网静态索引里的官方插件与工作流(幂等,可重复跑)
    gen-jwt-key      生成一把 Ed25519 私钥(PEM),输出到文件
    check-config     按生产要求检查环境变量,缺什么说什么
    dev-seed         本地开发:官方条目 + 开发账号 + 示例工作流 / 插件 / 统计 / 画板(幂等,只在 development 下)
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from sqlalchemy import select

from community.config import load_settings

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def alembic_config(database_url: str):
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def migrate(database_url: str, revision: str = "head") -> None:
    from alembic import command

    command.upgrade(alembic_config(database_url), revision)


def _context():
    from community.context import Context

    return Context.build(load_settings())


def cmd_migrate(args: argparse.Namespace) -> int:
    settings = load_settings()
    migrate(settings.database_url, args.revision)
    print(f"数据库已升级到 {args.revision}")
    return 0


def _read_password(args: argparse.Namespace) -> str | None:
    if args.password_stdin:
        return sys.stdin.readline().rstrip("\n")
    if args.no_password:
        return None
    first = getpass.getpass("管理员密码(至少 8 位):")
    second = getpass.getpass("再输一遍:")
    if first != second:
        raise SystemExit("两次输入的密码不一致")
    return first


def cmd_create_admin(args: argparse.Namespace) -> int:
    from community.errors import ApiError
    from community.models import ROLE_ADMIN, User
    from community.security import hash_password, normalize_handle, normalize_phone

    ctx = _context()
    with ctx.sessions() as db:
        try:
            phone = normalize_phone(args.phone)
            handle = normalize_handle(args.handle)
        except ApiError as exc:
            raise SystemExit(f"参数不对:{exc.code}") from exc
        user = db.scalars(select(User).where(User.phone == phone)).first()
        if user is None:
            if db.scalars(select(User).where(User.handle == handle)).first() is not None:
                raise SystemExit(f"用户名 {handle} 已经被另一个账号占用")
            password = _read_password(args)
            user = User(handle=handle, display_name=handle, phone=phone, password_hash=hash_password(password) if password else None)
            db.add(user)
            action = "建好了"
        else:
            action = "已有这个手机号的账号,提成了"
        user.role = ROLE_ADMIN
        db.commit()
        print(f"{action}管理员:@{user.handle}")
    return 0


def cmd_set_role(args: argparse.Namespace) -> int:
    from community.models import ROLES, User

    if args.role not in ROLES:
        raise SystemExit(f"角色只能是 {' / '.join(ROLES)}")
    ctx = _context()
    with ctx.sessions() as db:
        user = db.scalars(select(User).where(User.handle == args.handle.lower())).first()
        if user is None:
            raise SystemExit(f"没有用户 @{args.handle}")
        user.role = args.role
        db.commit()
        print(f"@{user.handle} 现在是 {args.role}")
    return 0


def cmd_seed_official(args: argparse.Namespace) -> int:
    from community.catalog import seed_official

    ctx = _context()
    root = Path(args.catalog_dir or ctx.settings.official_catalog_dir)
    if not (root / "plugins" / "registry.json").is_file():
        raise SystemExit(f"{root} 下没有 plugins/registry.json —— 用 --catalog-dir 指到官网的 public 目录")
    with ctx.sessions() as db:
        report = seed_official(ctx, db, root)
    print(f"新建 {len(report.created)} 项,新版本 {len(report.new_versions)} 项,未变 {len(report.unchanged)} 项")
    for name in report.created + report.new_versions:
        print(f"  + {name}")
    return 0


def cmd_gen_jwt_key(args: argparse.Namespace) -> int:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    pem = Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    out = Path(args.out)
    if out.exists() and not args.force:
        raise SystemExit(f"{out} 已存在;确实要覆盖就加 --force(覆盖后所有访问令牌立即失效)")
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(pem)
    print(f"私钥已写入 {out}(权限 600)。把 COMMUNITY_JWT_PRIVATE_KEY_FILE 指向它。")
    return 0


def cmd_check_config(_args: argparse.Namespace) -> int:
    problems = load_settings().problems()
    if problems:
        print("生产配置缺这些:")
        for one in problems:
            print(f"  - {one}")
        return 1
    print("配置齐了。")
    return 0


def cmd_dev_seed(_args: argparse.Namespace) -> int:
    from community.devseed import dev_seed

    settings = load_settings()
    if not settings.development:
        raise SystemExit("dev-seed 只在 COMMUNITY_ENV=development 下能跑")
    Path(settings.data_dir).mkdir(parents=True, exist_ok=True)
    migrate(settings.database_url)
    ctx = _context()
    with ctx.sessions() as db:
        report = dev_seed(ctx, db)
    for name in report.created:
        print(f"  + {name}")
    print("开发账号(只在本地开发库里有效):")
    print(f"  admin / demo,密码:{report.password}")
    print(f"  也写在 {report.credentials_file}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="community.cli", description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("migrate", help="升级数据库")
    p.add_argument("--revision", default="head")
    p.set_defaults(func=cmd_migrate)

    p = sub.add_parser("create-admin", help="建第一个管理员")
    p.add_argument("--handle", required=True)
    p.add_argument("--phone", required=True, help="管理员的手机号(找回密码、短信登录都靠它)")
    p.add_argument("--password-stdin", action="store_true", help="从标准输入读密码(脚本里用)")
    p.add_argument("--no-password", action="store_true", help="不设密码,只用短信验证码登录")
    p.set_defaults(func=cmd_create_admin)

    p = sub.add_parser("set-role", help="改角色")
    p.add_argument("handle")
    p.add_argument("role")
    p.set_defaults(func=cmd_set_role)

    p = sub.add_parser("seed-official", help="导入官方条目(幂等)")
    p.add_argument("--catalog-dir", default="", help="官网 public 目录(缺省取 COMMUNITY_OFFICIAL_CATALOG_DIR)")
    p.set_defaults(func=cmd_seed_official)

    p = sub.add_parser("gen-jwt-key", help="生成 Ed25519 私钥")
    p.add_argument("--out", required=True)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_gen_jwt_key)

    p = sub.add_parser("check-config", help="检查生产配置")
    p.set_defaults(func=cmd_check_config)

    p = sub.add_parser("dev-seed", help="本地开发的示例数据(幂等)")
    p.set_defaults(func=cmd_dev_seed)

    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
