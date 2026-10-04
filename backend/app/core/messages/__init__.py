"""后端文案表,按领域分片(此前是 core/i18n.py 里一个五千行的字面量)。

**新 key 加进它所属领域的那一片**;没有合适的就新开一片并登记进 `PARTS`。合并时 key 重名直接报错 ——
字面量里写两遍同一个 key,后一个会悄无声息地盖掉前一个。
"""

from __future__ import annotations

from app.core.messages import (
    agent,
    ai_chat,
    ai_runtime,
    audio,
    boards,
    confirmable,
    domain,
    entities,
    generation,
    integrations,
    node_catalog,
    plugins,
    routes,
    social,
    web_capture,
    workflows,
)

PARTS = (
    plugins, routes, confirmable, ai_chat, domain, integrations, ai_runtime, node_catalog, workflows,
    boards, audio, generation, agent, entities, social, web_capture,
)


def merged(*tables: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for table in tables:
        clash = out.keys() & table.keys()
        if clash:
            raise ValueError(f"duplicate message keys: {sorted(clash)}")
        out.update(table)
    return out
