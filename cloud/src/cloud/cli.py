"""运维命令:

    uv run python -m cloud.cli migrate            把数据库升到最新
    uv run python -m cloud.cli migrate --revision 0001
    uv run python -m cloud.cli stamp 0001         把 create_all 时代的库标到基线(一次性)

配置从 `CLOUD_*` 环境变量读,和 uvicorn 启动时同一份(见 `cloud/config.py`)。
"""

from __future__ import annotations

import argparse

from cloud.config import CloudConfig
from cloud.schema import stamp_database, upgrade_database


def database_url() -> str:
    config = CloudConfig.from_env()
    if not config.database_url:
        # SQLite 不会替我们建目录;uvicorn 入口会建,CLI 也要能单独跑。
        config.data_dir.mkdir(parents=True, exist_ok=True)
    return config.resolved_database_url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m cloud.cli", description="MosaelCloud 运维命令")
    commands = parser.add_subparsers(dest="command", required=True)

    migrate = commands.add_parser("migrate", help="升级数据库")
    migrate.add_argument("--revision", default="head", help="目标版本,缺省 head")

    stamp = commands.add_parser("stamp", help="把已有库标到某个版本,不执行迁移")
    stamp.add_argument("revision", help="这个库当前的基线版本")

    args = parser.parse_args(argv)
    url = database_url()
    if args.command == "migrate":
        upgrade_database(url, args.revision)
        print(f"数据库已升级到 {args.revision}")
    else:
        stamp_database(url, args.revision)
        print(f"数据库已标记为 {args.revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
