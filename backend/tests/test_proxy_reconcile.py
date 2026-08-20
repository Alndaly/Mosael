"""启动补齐扫描只救孤儿,不无限重试已判死刑的素材。

failed 是**判定过的终态**:源文件坏的素材每次转必败,启动扫描再替它排队等于无限重试
—— dev 模式每次热重启跑一轮,两个坏素材曾这样滚出上千条失败任务(任务中心 ×1232)。
pending 孤儿(重启害死守护线程留下的)和从没跑过的照旧要救。
"""

from __future__ import annotations

from app.domain.assets import proxies
from tests.util import fresh_client


def _make_asset(client, name: str, proxy_status: str | None) -> str:
    ws = client.post("/api/workspaces", json={"name": "W"}).json() if not hasattr(_make_asset, "_ws") else _make_asset._ws  # type: ignore[attr-defined]
    _make_asset._ws = ws  # type: ignore[attr-defined]
    from app.core.db import SessionLocal
    from app.db.models import Asset

    with SessionLocal() as db:
        asset = Asset(
            workspace_id=ws["id"],
            name=name,
            kind="video",
            file_key=f"media/{name}.mp4",
            media_info={"proxy_status": proxy_status} if proxy_status else {},
        )
        db.add(asset)
        db.commit()
        return asset.id


def test_启动补齐扫描跳过failed_只救孤儿(monkeypatch) -> None:
    client = fresh_client()
    failed_id = _make_asset(client, "坏素材", "failed")
    orphan_id = _make_asset(client, "孤儿", "pending")
    fresh_id = _make_asset(client, "没跑过", None)

    queued: list[str] = []
    monkeypatch.setattr(proxies.settings, "generate_proxies", True)
    monkeypatch.setattr(proxies, "start_proxy_job", lambda db, asset, **kw: queued.append(asset.id) or object())
    # 磁盘上都没有 proxy 文件(路径指向不存在的位置),全部走"要不要排队"的分支
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        proxies.reconcile_missing_proxies(db)

    assert failed_id not in queued, "failed 的素材被启动扫描重新排队 —— 无限重试回来了"
    assert orphan_id in queued
    assert fresh_id in queued
