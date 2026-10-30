"""运维命令:

    uv run python -m cloud.cli migrate            把数据库升到最新
    uv run python -m cloud.cli migrate --revision 0001
    uv run python -m cloud.cli stamp 0001         把 create_all 时代的库标到基线(一次性)
    uv run python -m cloud.cli seed-official --bundle official-bundle.json   补官方账号的分享(幂等)

官方中转 / 账号角色命令见 `cloud/relay_admin.py`(channel-key、mfa-key、admin-grant、admin-revoke、admin-list、
plan-set、subscribe、gift、model-set、price-set、channel-add、channel-list、balance)。

配置从 `CLOUD_*` 环境变量读,和 uvicorn 启动时同一份(见 `cloud/config.py`)。
"""

from __future__ import annotations

import argparse
import sys

from cloud.config import CloudConfig
from cloud.db import Database
from cloud.relay_admin import AdminError, register
from cloud.schema import stamp_database, upgrade_database


def load_config() -> CloudConfig:
    """和 uvicorn 启动读同一份配置。短官方密码等配置错误在这里就让命令失败。"""
    config = CloudConfig.from_env()
    if not config.database_url:
        # SQLite 不会替我们建目录;uvicorn 入口会建,CLI 也要能单独跑。
        config.data_dir.mkdir(parents=True, exist_ok=True)
    return config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m cloud.cli", description="MosaelCloud 运维命令")
    commands = parser.add_subparsers(dest="command", required=True)

    migrate = commands.add_parser("migrate", help="升级数据库")
    migrate.add_argument("--revision", default="head", help="目标版本,缺省 head")

    stamp = commands.add_parser("stamp", help="把已有库标到某个版本,不执行迁移")
    stamp.add_argument("revision", help="这个库当前的基线版本")

    seed = commands.add_parser(
        "seed-official", help="把 bundle 里的官方插件 / 工作流补进分享(幂等,只补缺)"
    )
    seed.add_argument("--bundle", required=True, help="bundle JSON 的路径")

    register(commands)

    args = parser.parse_args(argv)
    try:
        config = load_config()
    except ValueError as exc:
        # 配置错误(例如 CLOUD_OFFICIAL_PASSWORD 太短)不静默:命令以 2 退出并说清原因。
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2
    url = config.resolved_database_url
    if hasattr(args, "relay"):
        return _run_relay(args, config, url)
    if args.command == "migrate":
        upgrade_database(url, args.revision)
        print(f"数据库已升级到 {args.revision}")
    elif args.command == "stamp":
        stamp_database(url, args.revision)
        print(f"数据库已标记为 {args.revision}")
    else:
        # 新库也要能直接跑:和 uvicorn 启动一样先升到 head(迁移本身幂等)。
        from cloud.official import SeedError, load_bundle, seed_official

        try:
            bundle = load_bundle(args.bundle)
            upgrade_database(url)
            report = seed_official(
                url,
                bundle,
                handle=config.official_handle,
                email=config.official_email,
                password=config.official_password,
            )
        except SeedError as exc:
            print(f"种子命令失败: {exc}", file=sys.stderr)
            return 2
        print(report.summary())
    return 0


def _run_relay(args: argparse.Namespace, config: CloudConfig, url: str) -> int:
    """官方中转的运维命令:先把库升到最新(和 uvicorn 启动一样),在一个事务里做完、提交。"""
    if not getattr(args, "needs_db", True):
        print(args.relay(args, config, None))
        return 0
    upgrade_database(url)
    database = Database(url)
    try:
        with database.session() as db:
            try:
                print(args.relay(args, config, db))
            except AdminError as exc:
                db.rollback()
                print(f"没做: {exc}", file=sys.stderr)
                return 2
            db.commit()
    finally:
        database.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
