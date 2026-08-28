"""结构性约束:**字段说明不能只是把标签再说一遍。**

界面上每个字段是「标签 + 控件 + 一行小字」。那行小字挨着标签,如果它说的是同一件事,
读的人要多花一次注意力才发现自己什么也没得到 —— 十几个字段叠起来,整张表单就显得又长又空。
用户的原话:「不需要每个表单项都有底部的描述 有些太过累赘了」。

最露骨的是纯复述:标签「系统提示词」,下面一行小字还是「系统提示词」。次一等的是
「标签 + 一点新东西」——「供应商配置 id,留空自动选择」,前半截白占一行。

所以规矩是:**说明只说标签说不出的东西**(约束、默认值、格式、留空的含义、平台差异),
说不出新东西就不写。判据只认最保守的那条 —— 说明**以标签开头**就算复述;
中间提到标签(「多个用换行分隔」这种压根不提)不算。

顺带一提反向的坑:说明不是越少越好。同一轮里另有三个字段是**执行器有硬约束而表单只字未提**
(见 642e5c7),那种要补,不是要删。两件事的判据是同一句:这一行有没有说出新东西。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import re


def _norm(text: str) -> str:
    """比对前抹掉标点和空白 —— 「素材 id(逗号分隔)」和「素材id,逗号分隔」是同一种毛病。"""
    return re.sub(r"[\s,，。;；:：()（）]", "", text or "")


def test_说明不是把标签重说一遍() -> None:
    from app.domain.workflows import NODE_TYPES, config_label

    offenders = []
    for name, spec in sorted(NODE_TYPES.items()):
        for key, meta in (spec.get("config") or {}).items():
            meta = meta or {}
            description = (meta.get("description") or "").strip()
            if not description:
                continue
            label = config_label(key, meta) or ""
            if _norm(label) and _norm(description).startswith(_norm(label)):
                offenders.append(f"{name}.{key}:标签「{label}」,说明「{description}」")
    assert not offenders, (
        "这些说明以标签开头,那一截白占一行 —— 把复述的前缀去掉,只留标签说不出的那部分;"
        "去掉之后没剩下什么,就整条删掉:\n" + "\n".join(f"  {one}" for one in offenders)
    )


def test_判据本身认得出两种复述() -> None:
    """这条测试自己也可能写松。钉住判据:纯复述和带前缀的都要认出来,而只在中间提到标签的不算。"""
    assert _norm("系统提示词") == _norm("系统提示词")
    assert _norm("供应商配置id留空自动选择").startswith(_norm("供应商配置"))
    # 这一条是**好**说明的样子:标签说了「停止词」,它只说怎么写。
    assert not _norm("多个用换行分隔").startswith(_norm("停止词"))
