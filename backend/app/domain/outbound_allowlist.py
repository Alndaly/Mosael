"""内网访问的允许名单:用户给的地址(HTTP 请求节点、智能体的 http_request / fetch_url、从链接导入)
**可以**去的内网地址。判定在 core/outbound_guard,这里管存与推:

- 存在 DeploymentConfig(部署级的决定,和开放注册、共享文件夹同一类,经 domain/deployment 读写);
- 名单本身是进程级状态,住在 core/outbound_guard —— 用它的地方(websearch、run_http)不少拿不到 db 会话。
  启动时推一次、改完提交之后推一次,与重试次数(domain/ai_runtime)同一套做法。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core import outbound_guard
from app.core.unit_of_work import after_commit
from app.domain import deployment


def entries(db: Session) -> list[str]:
    return deployment.outbound_allowlist(db)


def save(db: Session, raw: list[str]) -> list[str]:
    """改名单。**调用方负责 `ensure_deployment_admin`。** 每一项都要写得对(写不对抛 AllowlistError,说清是哪一项);
    去重保序,存原文(去掉首尾空白)。提交之后对本进程生效;回滚了就不动进程里的那份。"""
    cleaned: list[str] = []
    for one in raw:
        text = str(one or "").strip()
        if not text:
            continue
        outbound_guard.parse_entry(text)
        if text not in cleaned:
            cleaned.append(text)
    deployment.set_outbound_allowlist(db, cleaned)
    after_commit(db, lambda: outbound_guard.set_allowlist(cleaned))
    return cleaned


def apply_to_process(db: Session) -> None:
    """启动时把库里那份推进进程。库里混进了一项写不对的(手改过库),那一项不算 —— 不让它拖垮启动。"""
    good: list[str] = []
    for one in entries(db):
        try:
            outbound_guard.parse_entry(one)
        except outbound_guard.AllowlistError:
            continue
        good.append(one)
    outbound_guard.set_allowlist(good)
