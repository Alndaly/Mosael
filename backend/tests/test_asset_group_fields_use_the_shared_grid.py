"""**一次挑一组素材**的字段,都必须走那一个共用的格子控件(`editor: "asset_grid"`)。

维护者看到的是两套控件:「LLM 生成」节点的「要模型看的图片」是一格一格的缩略图(挑、拖排序、直接传、
引用到的自动列在下面),而「AI 生成素材」的「输入素材」是两条下拉成行,实体保存 / 素材打标签 / 素材更新
的 `asset_ids` 干脆是一个手填引用的文本框 —— 同一件事(挑一组素材)三种长相。

于是那套格子控件抽成了共用件(`frontend/src/features/nodeForms/AssetGridField.tsx`),而**哪一种编
辑器由声明点名**:`editor: "asset_grid"`。这条测试守的就是这句话 —— 将来谁再给这种字段自绘一套、
忘了声明,这里就红。

判据是「这一格装的是**好几份素材**」,不是字段名长什么样:

- 名字以 `asset_ids` 结尾(`asset_ids` / `image_asset_ids`):复数,就是素材那一串;
- 声明了 `ref_assets_from`:提示词里引用到的素材会自动并进这一格,它得摆得下好几份;
- 声明了 `lines`:值是**行的列表**,每行一份素材(生成节点的「输入素材」)。

`entity_ids` / `model_ids` / `clip_ids` 不在内 —— 它们挑的是资产、3D 模型、时间线片段,不是素材;
单个 `asset_id` 也不在:那是「挑一份」,套格子网格没有意义。
"""

from __future__ import annotations

from typing import Any

from app.domain.workflows import NODE_TYPES

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True


def picks_asset_group(key: str, spec: Any) -> bool:
    """这一格是不是「一次挑一组素材」(判据见模块开头)。"""
    if not isinstance(spec, dict):
        return False
    #: 值是一整段代码的字段不会是素材格(插件硬把两种声明叠在一起时,代码优先)。
    if str(spec.get("type") or "") == "code":
        return False
    return key.endswith("asset_ids") or bool(spec.get("ref_assets_from")) or bool(spec.get("lines"))


def asset_group_fields() -> list[tuple[str, str, dict]]:
    return [
        (node_type, key, spec)
        for node_type, meta in NODE_TYPES.items()
        for key, spec in (meta.get("config") or {}).items()
        if picks_asset_group(key, spec)
    ]


def test_一次挑一组素材的字段都点名了共用格子控件() -> None:
    """**这一条就是那道棘轮**:4 个格子(生成节点的输入素材 + 三个 `asset_ids`)此前都没声明。"""
    found = asset_group_fields()
    #: 判据写歪了(一个都没匹配上)时,下面那一条会空转成绿的 —— 这里先拦住。
    assert found, "一个「一次挑一组素材」的字段都没找到:判据写歪了?"

    missing = [
        f"{node_type}.{key}"
        for node_type, key, spec in found
        if str(spec.get("editor") or "") != "asset_grid"
    ]
    assert missing == [], (
        "这些字段一次挑一组素材,却没点名共用的格子控件(editor: \"asset_grid\"):" + "、".join(missing)
    )


def test_共用格子控件只用在一次挑一组素材的字段上() -> None:
    """反方向:声明了 `asset_grid` 的字段也必须真的是「一次挑一组素材」。

    单向的棘轮挡不住另一半写歪 —— 把一个「挑一份」的字段(`asset_id`)也挂上格子网格,挑出来的是
    一格里的一份素材和一张卡片的交互对不上,而上面那一条照样是绿的。
    """
    stray = [
        f"{node_type}.{key}"
        for node_type, meta in NODE_TYPES.items()
        for key, spec in (meta.get("config") or {}).items()
        if isinstance(spec, dict)
        and str(spec.get("editor") or "") == "asset_grid"
        and not picks_asset_group(key, spec)
    ]
    assert stray == [], "这些字段不是一次挑一组素材,却挂了格子控件:" + "、".join(stray)
