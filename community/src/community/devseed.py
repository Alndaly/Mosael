"""本地开发用的示例数据:`uv run python -m community.cli dev-seed`。**只在 COMMUNITY_ENV=development 下能跑。**

做的事(幂等,跑几遍结果都一样):

- 导入官网静态索引里的官方插件与工作流(和生产的 seed-official 同一段代码);
- 两个账号:管理员 `admin`、普通用户 `demo`。密码第一次跑时随机生成,写进 `<数据目录>/dev-credentials.txt`
  并打印在终端上 —— 不写死在代码或文档里;
- 几个社区工作流(其中一个含运行代码节点)、一个审核通过的社区插件、一个待审核的插件;
- 近 30 天的下载 / 浏览 / 点赞(按天,有起伏),统计页和详情页的走势图有东西可画;
- 一张公开的画板分享:几张 Pillow 画的占位图、一张便签、一个文档格和连线。
"""

from __future__ import annotations

import io
import json
import random
import secrets
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from PIL import Image, ImageDraw
from sqlalchemy import select
from sqlalchemy.orm import Session

from community.catalog import seed_official
from community.context import Context
from community.db import utcnow
from community.models import (
    ROLE_ADMIN,
    ROLE_USER,
    VISIBILITY_PUBLIC,
    Item,
    ItemDailyStat,
    ItemVersion,
    Like,
    Share,
    ShareVersion,
    ShareVersionBlob,
    User,
)
from community.security import hash_password
from community.stats import refresh_trend, today
from community.submissions import Metadata, review, store_blob, submit_plugin, submit_workflow
from mosael_formats.board_snapshot import SCHEMA, validate_snapshot

CREDENTIALS_FILE = "dev-credentials.txt"
BOARD_KEY = "dev-seed-board-0001"
STAT_DAYS = 30

#: 示例账号的手机号:固定的示例号码,只存在于本地开发库里(短信走 console 发送器,不会真的发出去)。
USERS = {"admin": ("+8613800138000", ROLE_ADMIN), "demo": ("+8613800138001", ROLE_USER)}


@dataclass
class DevSeedReport:
    credentials_file: Path
    password: str
    created: list[str] = field(default_factory=list)


def _password(path: Path) -> str:
    """开发账号的密码:第一次随机生成并写进文件,之后都从文件读 —— 重跑不换密码。"""
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("password="):
                return line.split("=", 1)[1].strip()
    password = secrets.token_urlsafe(12)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# 本地开发账号(dev-seed 生成,只在这台机器的开发库里有效)\n"
        f"admin=admin\ndemo=demo\npassword={password}\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return password


def _user(db: Session, handle: str, phone: str, role: str, password: str, report: DevSeedReport) -> User:
    user = db.scalars(select(User).where(User.handle == handle)).first()
    if user is None:
        user = User(handle=handle, display_name=handle.capitalize(), phone=phone)
        db.add(user)
        report.created.append(f"user:{handle}")
    user.role = role
    user.password_hash = hash_password(password)
    db.flush()
    return user


def _workflow_bytes(title: str, *, with_code: bool) -> bytes:
    nodes = [
        {"id": "start", "type": "start", "name": "开始", "position": {"x": 40, "y": 120}, "config": {}},
        {"id": "write", "type": "template", "name": "写一段话", "position": {"x": 320, "y": 120},
         "config": {"template": f"{title}:{{{{start.topic}}}}"}},
    ]
    edges = [{"id": "e1", "source": "start", "target": "write"}]
    if with_code:
        nodes.append({"id": "count", "type": "code", "name": "数一数字数", "position": {"x": 600, "y": 120},
                      "config": {"code": "output = len(input['text'])", "input": {"text": "{{write.text}}"}}})
        edges.append({"id": "e2", "source": "write", "target": "count"})
    return json.dumps(
        {"format": "mosael-workflow", "version": 1, "name": title, "description": f"示例工作流:{title}", "graph": {"nodes": nodes, "edges": edges}},
        ensure_ascii=False,
    ).encode("utf-8")


def _plugin_zip(plugin_id: str, version: str, name: str) -> bytes:
    import zipfile

    manifest = {
        "id": plugin_id,
        "name": {"zh": name, "en": name},
        "version": version,
        "permissions": ["network:example"],
        "homepage": "https://example.com",
        "author": {"name": "Demo", "url": "https://example.com"},
        "runtime": {"kind": "process", "entry": "main.py"},
        "skills": [{"name": "greet", "description": {"zh": f"{name}:示例插件", "en": f"{name}: a sample plugin"}}],
        "tools": {"declare": [{"name": "greet", "label": {"zh": "打招呼", "en": "Greet"}, "effects": "none"}]},
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mosael.plugin.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr("main.py", "import json, sys\nprint(json.dumps({'text': 'hello'}))\n")
    return buffer.getvalue()


def _placeholder(color: tuple[int, int, int], label: str, size=(640, 400)) -> bytes:
    image = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(image)
    for offset in range(0, size[0] + size[1], 40):
        draw.line([(offset, 0), (offset - size[1], size[1])], fill=tuple(min(255, c + 25) for c in color), width=8)
    draw.text((24, 24), label, fill=(255, 255, 255))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _item_owned(db: Session, owner: User, kind: str, slug_or_title: str) -> Item | None:
    """按 slug 或标题认这个人名下已有的一项(标题是 JSON 列,在 Python 里比,两种库都一样)。"""
    for item in db.scalars(select(Item).where(Item.owner_id == owner.id, Item.kind == kind)):
        if slug_or_title in (item.slug, item.title):
            return item
    return None


def _seed_stats(db: Session, item: Item, rng: random.Random) -> None:
    """近 30 天按天的数:写定值而不是累加,重跑结果一样。"""
    start = today() - timedelta(days=STAT_DAYS - 1)
    base = rng.randint(2, 12)
    totals = {"downloads": 0, "views": 0, "likes": 0}
    for offset in range(STAT_DAYS):
        day = start + timedelta(days=offset)
        wave = 1 + (offset % 7 in (5, 6))  # 周末多一点
        values = {
            "downloads": max(0, int(base * wave * rng.uniform(0.3, 1.4))),
            "views": max(0, int(base * 6 * wave * rng.uniform(0.5, 1.5))),
            "likes": max(0, int(base * wave * rng.uniform(0.0, 0.5))),
        }
        row = db.get(ItemDailyStat, (item.id, day))
        if row is None:
            row = ItemDailyStat(item_id=item.id, day=day, downloads=0, views=0, likes=0)
            db.add(row)
        for key, value in values.items():
            setattr(row, key, value)
            totals[key] += value
    db.flush()
    item.downloads_total, item.views_total = totals["downloads"], totals["views"]
    item.likes_total = totals["likes"]
    refresh_trend(db, item)


def _seed_share(ctx: Context, db: Session, owner: User, report: DevSeedReport) -> None:
    if db.scalars(select(Share).where(Share.owner_id == owner.id, Share.board_key == BOARD_KEY)).first() is not None:
        return
    images = [
        ("i1", _placeholder((88, 86, 214), "Moodboard A"), "参考图 A"),
        ("i2", _placeholder((214, 86, 140), "Moodboard B"), "参考图 B"),
        ("i3", _placeholder((40, 160, 120), "Moodboard C"), "参考图 C"),
    ]
    items: list[dict] = []
    for index, (item_id, data, title) in enumerate(images):
        blob = store_blob(ctx, db, owner, data, "image/png")
        items.append({
            "id": item_id, "kind": "image", "x": index * 300, "y": 0, "width": 260, "height": 163, "title": title,
            "media": {"sha256": blob.sha256, "content_type": "image/png", "width": 640, "height": 400},
        })
    items.append({"id": "n1", "kind": "note", "x": 0, "y": 220, "width": 240, "height": 140,
                  "text": "这是一张示例便签:把三张参考图的配色统一成冷色调。", "color": "yellow"})
    items.append({"id": "d1", "kind": "document", "x": 300, "y": 220, "width": 520, "height": 320, "title": "分镜说明",
                  "markdown": "# 分镜说明\n\n1. 开场:远景\n2. 推近到主角\n3. 结尾:字幕淡出\n", "revision": 3})
    snapshot = {
        "schema": SCHEMA,
        "viewport": {"x": 0, "y": 0, "zoom": 0.8},
        "items": items,
        "edges": [{"id": "e1", "source": "n1", "target": "i1"}, {"id": "e2", "source": "d1", "target": "i2"}],
    }
    summary = validate_snapshot(snapshot, max_items=ctx.settings.share_max_items)
    now = utcnow()
    share = Share(slug="demo-board", owner_id=owner.id, board_key=BOARD_KEY, title="示例画板:短片前期", visibility=VISIBILITY_PUBLIC,
                  created_at=now, updated_at=now)
    db.add(share)
    db.flush()
    version = ShareVersion(share_id=share.id, number=1, snapshot=snapshot, item_count=summary.item_count, total_bytes=0, created_at=now)
    db.add(version)
    db.flush()
    for sha in summary.hashes:
        db.add(ShareVersionBlob(version_id=version.id, sha256=sha))
    share.current_version_id = version.id
    report.created.append("share:demo-board")


def dev_seed(ctx: Context, db: Session) -> DevSeedReport:
    if not ctx.settings.development:
        raise RuntimeError("dev-seed only runs with COMMUNITY_ENV=development")
    seed_official(ctx, db, Path(ctx.settings.official_catalog_dir))
    credentials = Path(ctx.settings.data_dir) / CREDENTIALS_FILE
    report = DevSeedReport(credentials_file=credentials, password=_password(credentials))
    admin = _user(db, "admin", *USERS["admin"], report.password, report)
    demo = _user(db, "demo", *USERS["demo"], report.password, report)

    workflows = [("短视频开场生成", False), ("口播稿润色", False), ("批量统计文案字数", True)]
    for title, with_code in workflows:
        if _item_owned(db, demo, "workflow", title) is None:
            submit_workflow(ctx, db, demo, _workflow_bytes(title, with_code=with_code),
                            Metadata(title=title, summary=f"{title}的示例", tags=["示例", "dev"]))
            report.created.append(f"workflow:{title}")

    if _item_owned(db, demo, "plugin", "dev.demo.greeter") is None:
        _, version = submit_plugin(ctx, db, demo, _plugin_zip("dev.demo.greeter", "1.0.0", "Greeter"), Metadata(tags=["示例"]))
        review(db, version, admin, approve=True, note="dev-seed")
        report.created.append("plugin:dev.demo.greeter")
    if _item_owned(db, demo, "plugin", "dev.demo.pending") is None:
        submit_plugin(ctx, db, demo, _plugin_zip("dev.demo.pending", "0.1.0", "Pending Plugin"), Metadata())
        report.created.append("plugin:dev.demo.pending (pending review)")

    rng = random.Random(20260927)
    items = list(db.scalars(select(Item).where(Item.current_version_id.is_not(None)).order_by(Item.slug)))
    for item in items[:8]:
        if db.get(Like, (admin.id, item.id)) is None:
            db.add(Like(user_id=admin.id, item_id=item.id))
    db.flush()
    for item in items:
        _seed_stats(db, item, rng)

    _seed_share(ctx, db, demo, report)
    # 让「注册」走势也有几天的数:两个开发账号的注册时间落在最近几天(只改开发库)。
    for offset, user in enumerate((admin, demo)):
        user.created_at = min(user.created_at, utcnow() - timedelta(days=3 + offset * 5))
    db.commit()
    assert db.scalar(select(ItemVersion).limit(1)) is not None
    return report


__all__ = ["CREDENTIALS_FILE", "DevSeedReport", "dev_seed"]
