"""重启真的把那两处收尾了 —— 不只是"登记过"。

`test_every_in_flight_row_has_someone_to_settle_it` 问的是「你登记了吗」;这条问的是
「登记的那个函数真的管用吗」。两条缺一不可:一个空函数也能通过前一条。
"""

from __future__ import annotations

import json

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import PluginInstance, PluginInvocation, PluginPackage
from app.domain.blender.bridge import reconcile_orphaned_transfers
from app.domain.restart import reconcile_after_restart
from tests.util import fresh_client


def test_停在running的插件调用被判成失败() -> None:
    """调用**之前**先落一行 running,然后才去跑子进程。后端在这中间被杀(开发态 --reload
    每改一次文件就是一次),这一行永远停在 running,插件页一直把它列出来。"""
    fresh_client()
    with SessionLocal() as db:
        db.add(PluginPackage(id="dev.test.pkg", name="测试包", version="0.1.0"))
        db.flush()  # 外键先落地,否则下面那行插不进去
        instance = PluginInstance(package_id="dev.test.pkg", name="测试接入")
        db.add(instance)
        db.flush()
        db.add(PluginInvocation(instance_id=instance.id, tool_name="do", status="running", input={}, output={}))
        db.add(PluginInvocation(instance_id=instance.id, tool_name="done", status="succeeded", input={}, output={}))
        db.commit()

    with SessionLocal() as db:
        settled = reconcile_after_restart(db)
    assert settled["plugin_invocations"] == 1

    with SessionLocal() as db:
        rows = {one.tool_name: one for one in db.query(PluginInvocation).all()}
        # 跑到一半的那条判失败,并且说清为什么 —— 空着的话界面上只是"失败了",用户无从判断
        # 要不要重试。
        assert rows["do"].status == "failed" and "重启" in (rows["do"].error or "")
        # 已经有结果的那条**不许动**:收尾只碰进行中的,不是把这张表清一遍。
        assert rows["done"].status == "succeeded"


def test_插件调用的重启原因跟着界面语言(monkeypatch) -> None:
    """此前这一句是写死的中文 —— 英文界面上照样冒出一句「后端重启,这次调用没有结果」。"""
    from app.core import i18n
    from app.domain.plugins.tools import reconcile_orphaned_invocations

    fresh_client()
    with SessionLocal() as db:
        db.add(PluginPackage(id="dev.test.pkg", name="测试包", version="0.1.0"))
        db.flush()
        instance = PluginInstance(package_id="dev.test.pkg", name="测试接入")
        db.add(instance)
        db.flush()
        db.add(PluginInvocation(instance_id=instance.id, tool_name="do", status="running", input={}, output={}))
        db.commit()
        i18n.set_current_locale("en")
        try:
            assert reconcile_orphaned_invocations(db) == 1
        finally:
            i18n.set_current_locale(i18n.DEFAULT_LOCALE)
        row = db.query(PluginInvocation).one()
        assert "restarted" in (row.error or "")


def test_停在sending的blender互通被判成失败() -> None:
    """`send()` 先写 status='sending' 再去跑 Blender,正常路径靠 finally 改写 —— 进程被杀就
    写不到。留下来的那份 `receive()` 接不回来(它要求 ready),而 `history()` 会永远列着它。"""
    fresh_client()
    base = settings.data_dir / "blender-bridge" / "ws" / "scene"
    stuck, done = base / "aaa", base / "bbb"
    for folder, status in ((stuck, "sending"), (done, "ready")):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "transfer.json").write_text(
            json.dumps({"id": folder.name, "owner": "u", "status": status}), encoding="utf-8"
        )

    assert reconcile_orphaned_transfers() == 1

    healed = json.loads((stuck / "transfer.json").read_text(encoding="utf-8"))
    assert healed["status"] == "failed" and "重启" in healed["error"]
    # 已经 ready 的那份原样留着 —— 用户还要把它接回来。
    assert json.loads((done / "transfer.json").read_text(encoding="utf-8"))["status"] == "ready"


def test_没有blender目录时不炸() -> None:
    """启动收尾在**每一次**启动都跑,包括从来没用过 Blender 互通的机器上。"""
    fresh_client()
    assert reconcile_orphaned_transfers() == 0
