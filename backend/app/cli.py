"""后端命令行:不经过界面、直接对这台机器上的数据目录做的管理员的事。

现在两件:

- `reset-password` —— 唯一的部署管理员忘了密码时,界面上没有任何人能替他重置(管理页的「重置密码」
  要先登录成部署管理员),整台部署就锁在外面。能在这台机器上跑命令的人本来就能读写这份数据目录,
  所以由它兜底;
- `feishu-worker <bot_id>` —— 一条飞书长连接。**打包后的后端里没有 `app` 这个包可 import**(它是冻结
  二进制),所以长连接子进程不能再走 `python -m app.integrations.feishu.worker`:那条命令在打包版里
  是 `ModuleNotFoundError: app.integrations`,进程秒退、设置页写着「长连接进程退出(code 2)」
  (2026-10-23 真机)。改成用同一个二进制 + 管理命令起,开发版和打包版走同一条路。

用法:
  开发环境      cd backend && uv run python -m app.cli reset-password <用户名>
  打包后的应用  <安装目录>/…/backend/mosael-backend/mosael-backend reset-password <用户名>
               (macOS:/Applications/Mosael.app/Contents/Resources/backend/mosael-backend/mosael-backend)
数据目录和后端是同一份:默认 ~/.mosael,设了 MOSAEL_DATA_DIR 就用它。后端开着也能跑。
"""

from __future__ import annotations

import argparse
import sys

#: 登录接口要求的最短密码(api/schemas/identity.AuthCredentials)。
_MIN_PASSWORD = 4


def _reset_password(args: argparse.Namespace) -> int:
    from app.core.db import SessionLocal
    from app.db.models import User
    from app.domain import members

    if args.password is not None and len(args.password) < _MIN_PASSWORD:
        print(f"密码至少 {_MIN_PASSWORD} 位 / The password needs at least {_MIN_PASSWORD} characters.", file=sys.stderr)
        return 2
    username = members.normalize_username(args.username)
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username).one_or_none()
        if user is None:
            known = ", ".join(sorted(name for (name,) in db.query(User.username))) or "—"
            print(f"没有用户名为「{username}」的账号。这台部署上的账号:{known}", file=sys.stderr)
            print(f"No account named '{username}'. Accounts on this deployment: {known}", file=sys.stderr)
            return 1
        password = members.reset_password(db, user, args.password)
        db.commit()
    print(f"已重置「{username}」的密码,他已经登录着的会话全部作废。")
    print(f"Password for '{username}' reset; every session signed in as them has been signed out.")
    print(f"新密码 / New password: {password}")
    if args.password is None:
        print("登录后在「设置 → 账户」里改成你自己的。/ Sign in and change it in Settings → Account.")
    return 0


COMMANDS = {"reset-password", "feishu-worker"}


def _feishu_worker(args: argparse.Namespace) -> int:
    """跑一条长连接,直到 stdin 关掉(主进程退出)或进程被杀。"""
    from app.integrations.feishu.worker import main as run_worker

    run_worker(args.bot_id)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mosael-backend", description="Mosael 后端的管理命令 / Mosael backend admin commands")
    sub = parser.add_subparsers(dest="command", required=True)
    reset = sub.add_parser(
        "reset-password",
        help="重置一个账号的密码(忘了密码时) / reset an account's password",
        description="重置一个账号的密码并让它已登录的会话全部作废。不给 --password 就生成一个临时密码。",
    )
    reset.add_argument("username", help="要重置的用户名 / the username")
    reset.add_argument("--password", help="直接设成这个密码(不给就随机生成) / set this password instead of a random one")
    reset.set_defaults(handler=_reset_password)
    worker = sub.add_parser(
        "feishu-worker",
        help="跑一条飞书长连接(内部使用:后端为每个机器人起一个) / run one Feishu long connection (internal)",
        description="由后端按机器人拉起的长连接子进程入口;凭据从 stdin 读,不经过命令行。",
    )
    worker.add_argument("bot_id", help="机器人 id / the bot id")
    worker.set_defaults(handler=_feishu_worker)
    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
