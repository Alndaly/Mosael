"""画板上每一个内容变换都住在内容格上:能力挂在它吃的那几种格子上,生成器挂在它产出的那种空格子上。

ADR 0025 修订「能力住在内容格上」:画板上没有单独的工具格。一个节点(内置的,或插件工具)只要过了
`boards.transforms.content_transform_gap`,就必须**至少挂在一种内容格上** —— 否则它在注册表里、却在画板上
哪儿也点不到;而没有哪个产出者挂在 `action` 上(那种格子不存在了)。判据从声明推,不是一张清单:

· 能力(`ability`):挂在它吃内容的那个字段收得下的格子上,每一种宿主都说得出宿主的内容填进哪个字段;
· 生成器(`slot`):能填空槽,挂在图片 / 视频 / 音频这几种素材格上。

同一条对着内置节点、测试里的插件工具和仓库里随包的插件清单各查一遍。
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.util import fresh_client

RATCHET = True

#: 画板上装内容的几种格子:能力和生成器只能挂在这些上面。
CONTENT_KINDS = {"note", "document", "image", "video", "audio", "scene"}
MEDIA_KINDS = {"image", "video", "audio"}


def _check(producer_id: str, meta: dict) -> None:
    from app.domain.boards.canvas import ITEM_KINDS
    from app.domain.boards.transforms import ABILITY, SLOT, board_hosts, board_role, host_field, host_fields

    hosts = board_hosts(meta)
    role = board_role(meta)
    assert hosts, f"{producer_id} 过了内容变换的规矩,却哪一种格子都挂不上"
    assert "action" not in hosts and "action" not in ITEM_KINDS, f"{producer_id} 挂在已经撤下的工具格上"
    assert set(hosts) <= CONTENT_KINDS, (producer_id, hosts)
    assert role in (ABILITY, SLOT), (producer_id, role)
    if role == ABILITY:
        fields = host_fields(meta)
        assert set(fields) == set(hosts), f"{producer_id} 有的宿主说不出内容填进哪个字段:{hosts} / {fields}"
        for kind in hosts:
            assert host_field(meta, kind) in (meta.get("config") or {}), (producer_id, kind)
    else:
        assert set(hosts) <= MEDIA_KINDS, f"{producer_id} 是生成器,却挂在不装素材的格子上:{hosts}"
        assert host_fields(meta) == {}


def test_注册表里每一个节点产出者都挂在内容格上() -> None:
    from app.core.db import SessionLocal
    from app.domain.boards import producers
    from app.domain.boards.transforms import ABILITY, SLOT

    fresh_client()
    with SessionLocal() as db:
        registry = producers.list_producers(db, None)
    assert all("action" not in one.hosts for one in registry), "有产出者挂在已经撤下的工具格上"
    for producer in registry:
        if producer.id.startswith("node:"):
            _check(producer.id, producer.meta or {})
            #: 能力不填空槽;生成器就是空槽的一种填法(和配音 / 生成一起出现在切换里)。
            assert producer.fills_empty_slot == (producer.role == SLOT), producer.id
        else:
            assert producer.role != ABILITY, f"内置的 {producer.id} 是它那一格自己的产出者"


def test_测试插件和随包插件里能上画板的工具_都挂在内容格上() -> None:
    from app.domain.boards.transforms import is_content_transform
    from app.domain.plugins.nodes import node_meta
    from tests.test_board_producers import PLUGIN_TOOLS

    declared = [("test." + one["name"], one) for one in PLUGIN_TOOLS]
    root = Path(__file__).resolve().parents[2] / "plugins"
    for path in sorted(root.glob("*/*/mosael.plugin.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        declared += [(f"{manifest['id']}.{one['name']}", one) for one in (manifest.get("tools") or {}).get("declare") or []]
    checked = 0
    for name, tool in declared:
        meta = node_meta(tool)
        if not tool.get("internal") and is_content_transform(meta):
            _check(name, meta)
            checked += 1
    assert checked >= 5, "扫描面站不住:一个能上画板的插件工具都没找到"
