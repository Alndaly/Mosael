"""引用表(`record_references`)的抽取规则与维护。

JSON 里点名别的记录的地方不少:画布的格子、工作流节点的配置、生成请求、3D 场景、定时任务。此前「谁还指着它」
靠把整列 JSON 转成字符串 `LIKE '%id%'` 粗筛,或者逐行在 Python 里遍历;每处各写一份,规则也各自一份。
现在规则只在这里写一次,结果落进一张有索引的表:

- **写**:每次 flush 时,新建 / 改了 JSON / 删掉的来源行,在同一个事务里把它的引用整份重写(`_sync`)。
  不经 ORM 的批量改写(迁移的原生 SQL)不触发它 —— 所以
- **重建**:启动时按 `EXTRACTOR_VERSION` 对账,不一致就整张重建(`reindex`,挂在迁移计划最后的对账步骤里)。
  改了抽取规则就把版本号加一。

只依赖 db 层(迁移要调它,而迁移不许依赖还在演进的领域代码)。
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from sqlalchemy import JSON, Text, delete, event, insert, select, type_coerce
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, attributes

from app.db.model_slices.references import RecordReference, RecordReferenceIndex

#: 抽取规则的版本。**改了下面任何一条抽取规则就加一**,启动时整张表按新规则重建。
EXTRACTOR_VERSION = 2

Ref = tuple[str, str, str]  # (target_kind, target_id, how)


def split_ids(value: Any) -> list[str]:
    """一串 id,或者逗号 / 换行分隔的一段字(工作流的模板字段插值之后就是这样)。去重保序。"""
    if value is None:
        return []
    if isinstance(value, str):
        parts: list[Any] = value.replace("，", ",").replace("\n", ",").split(",")
    elif isinstance(value, (list, tuple)):
        parts = []
        for one in value:
            parts.extend(one if isinstance(one, (list, tuple)) else [one])
    else:
        return []
    out: list[str] = []
    for part in parts:
        text = str(part or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _literal(value: Any) -> str | None:
    """一个写死的 id。模板插值(`{{…}}`)不是引用 —— 运行时才知道指着谁。"""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value and "{{" not in value and len(value) <= 64 else None


def _literals(value: Any) -> list[str]:
    return [one for one in (_literal(part) for part in split_ids(value)) if one]


def _dicts(value: Any) -> Iterator[dict[str, Any]]:
    for one in value if isinstance(value, list) else []:
        if isinstance(one, dict):
            yield one


# ---------------- 各来源的抽取规则 ----------------

#: 画布格子上指向别处的字段 → 目标种类。
_CANVAS_FIELDS = {
    "asset_id": "asset",
    "entity_id": "entity",
    "scene_id": "scene",
    "sequence_id": "sequence",
    "note_id": "note",
}


def board_refs(canvas: Any) -> Iterator[Ref]:
    """画布:一格就是它(`cell`),某一格的提示词里 @ 了它(`mention`),或便签上的字是从那篇笔记摘来的(`source`)。"""
    for item in _dicts((canvas or {}).get("items") if isinstance(canvas, dict) else None):
        for field, kind in _CANVAS_FIELDS.items():
            target = _literal(item.get(field))
            if target:
                yield kind, target, "cell"
        source = item.get("source_note") if isinstance(item.get("source_note"), dict) else {}
        target = _literal(source.get("note_id"))
        if target:
            yield "note", target, "source"
        form = item.get("form") if isinstance(item.get("form"), dict) else {}
        for target in _literals(form.get("mentioned_entity_ids")):
            yield "entity", target, "mention"


#: 工作流节点配置里指向别处的字段 → 目标种类。多值的字段(`*_ids`)按 split_ids 拆。
_NODE_FIELDS = {
    "asset_id": "asset",
    "audio_asset_id": "asset",
    "asset_ids": "asset",
    "entity_id": "entity",
    "entity_ids": "entity",
    "sequence_id": "sequence",
    "scene_id": "scene",
    "note_id": "note",
    "workflow_id": "workflow",
}


def workflow_refs(graph: Any) -> Iterator[Ref]:
    for node in _dicts((graph or {}).get("nodes") if isinstance(graph, dict) else None):
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        for field, kind in _NODE_FIELDS.items():
            for target in _literals(config.get(field)):
                yield kind, target, "node"


def generation_refs(request: Any) -> Iterator[Ref]:
    """生成请求里点名的资产(人物 / 场景 / 道具)。"""
    for row in _dicts((request or {}).get("entities") if isinstance(request, dict) else None):
        target = _literal(row.get("id"))
        if target:
            yield "entity", target, ""


def scene_refs(content: Any) -> Iterator[Ref]:
    """3D 场景里摆着的导入模型。"""
    for obj in _dicts((content or {}).get("objects") if isinstance(content, dict) else None):
        target = _literal(obj.get("model_id"))
        if target:
            yield "scene_model", target, ""


def scheduled_task_refs(kind: Any, payload: Any) -> Iterator[Ref]:
    if kind == "workflow" and isinstance(payload, dict):
        target = _literal(str(payload.get("workflow_id") or ""))
        if target:
            yield "workflow", target, ""


@dataclass(frozen=True)
class Source:
    kind: str
    model: Callable[[], type]
    #: 抽取规则读的列。任何一列变了,这一行的引用就整份重写。
    columns: tuple[str, ...]
    extract: Callable[..., Iterable[Ref]]


def _model(module: str, name: str) -> Callable[[], type]:
    """按切片取模型(不经 app.db.models:那个入口反过来要装配这里)。"""

    def load() -> type:
        return getattr(importlib.import_module(f"app.db.model_slices.{module}"), name)

    return load


SOURCES: tuple[Source, ...] = (
    Source("board", _model("boards", "Board"), ("canvas",), board_refs),
    Source("workflow", _model("workflows", "Workflow"), ("graph",), workflow_refs),
    Source("generation", _model("generation", "GenerationJob"), ("request",), generation_refs),
    Source("scene", _model("scenes", "Scene3D"), ("content",), scene_refs),
    Source("scheduled_task", _model("scheduler", "ScheduledTask"), ("kind", "payload"), scheduled_task_refs),
)


def refs_of(source: Source, row: Any) -> set[Ref]:
    return set(source.extract(*(getattr(row, column) for column in source.columns)))


def _rows(source: Source, row: Any) -> list[dict[str, str]]:
    return [
        {"source_kind": source.kind, "source_id": row.id, "target_kind": kind, "target_id": target,
         "how": how, "workspace_id": row.workspace_id}
        for kind, target, how in sorted(refs_of(source, row))
    ]


# ---------------- 维护 ----------------


def _source_of(obj: Any) -> Source | None:
    for source in SOURCES:
        if isinstance(obj, source.model()):
            return source
    return None


def _changed(obj: Any, source: Source) -> bool:
    """这些列动过没有。`flag_modified` 标过的(就地改了 JSON)没有前后值可比,但会进 committed_state。"""
    state = attributes.instance_state(obj)
    return any(
        column in state.committed_state or attributes.get_history(obj, column).has_changes()
        for column in source.columns
    )


@event.listens_for(Session, "after_flush")
def _sync(session: Session, _context: Any) -> None:
    """这一次 flush 里新建、改了 JSON、删掉的来源行:引用整份重写。和数据在同一个事务里。"""
    stale: dict[str, set[str]] = {}
    fresh: list[dict[str, str]] = []
    for obj in session.deleted:
        source = _source_of(obj)
        if source is not None:
            stale.setdefault(source.kind, set()).add(obj.id)
    for obj in [*session.new, *session.dirty]:
        source = _source_of(obj)
        if source is None or obj in session.deleted:
            continue
        if obj in session.new or _changed(obj, source):
            stale.setdefault(source.kind, set()).add(obj.id)
            fresh.extend(_rows(source, obj))
    if not stale:
        return
    connection = session.connection()
    for kind, ids in stale.items():
        connection.execute(
            delete(RecordReference).where(RecordReference.source_kind == kind, RecordReference.source_id.in_(ids))
        )
    if fresh:
        connection.execute(insert(RecordReference), fresh)


def resync(session: Session, source_kind: str, source_id: str) -> None:
    """按库里的当前值重写一行来源的引用。给**绕过 flush 的写**用:比较并交换式的 `update(Board)…` 不经过
    ORM 的脏检查,`_sync` 看不见它(棘轮:tests/test_record_references.py 要求这类写就地调它)。"""
    source = next(one for one in SOURCES if one.kind == source_kind)
    model = source.model()
    row = session.execute(
        select(model.id, model.workspace_id, *(getattr(model, column) for column in source.columns)).where(model.id == source_id)
    ).first()
    session.execute(
        delete(RecordReference).where(RecordReference.source_kind == source_kind, RecordReference.source_id == source_id)
    )
    fresh = _rows(source, row) if row is not None else []
    if fresh:
        session.execute(insert(RecordReference), fresh)


def _raw(model: type, column: str) -> Any:
    attribute = getattr(model, column)
    return type_coerce(attribute, Text).label(column) if isinstance(attribute.type, JSON) else attribute


def _decoded(model: type, column: str, value: Any) -> Any:
    if not isinstance(getattr(model, column).type, JSON) or not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except ValueError:
        return None


def reindex(connection: Connection) -> bool:
    """按当前抽取规则整张重建。版本号对得上就什么都不做;返回这一次重建了没有。"""
    current = connection.execute(select(RecordReferenceIndex.version).where(RecordReferenceIndex.id == 1)).scalar()
    if current == EXTRACTOR_VERSION:
        return False
    connection.execute(delete(RecordReference))
    for source in SOURCES:
        model = source.model()
        # 按原文读,自己解析:老库里 JSON 列可能躺着空串或半截文本,一行读坏不该让启动失败。
        columns = [model.id, model.workspace_id, *(_raw(model, column) for column in source.columns)]
        batch: list[dict[str, str]] = []
        for row in connection.execute(select(*columns)):
            values = SimpleNamespace(id=row[0], workspace_id=row[1],
                                     **{column: _decoded(model, column, value)
                                        for column, value in zip(source.columns, row[2:], strict=True)})
            batch.extend(_rows(source, values))
            if len(batch) >= 1000:
                connection.execute(insert(RecordReference), batch)
                batch = []
        if batch:
            connection.execute(insert(RecordReference), batch)
    connection.execute(delete(RecordReferenceIndex))
    connection.execute(insert(RecordReferenceIndex), [{"id": 1, "version": EXTRACTOR_VERSION}])
    return True
