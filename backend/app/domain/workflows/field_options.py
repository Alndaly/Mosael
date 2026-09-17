"""节点字段的**动态选项**:清单要现查、而且可能跟着另一个字段变的那种。

字段在 NODE_TYPES 里声明 `options_from: "<来源名>"`,前端对任何带这个声明的字段都走同一个
接口(`GET /api/workflows/field-options`),把它 `depends_on` 的那个字段的当前值作为 `parent`
带上。前端因此**不认识任何具体节点** —— 此前语音合成和字幕配音的音色、引擎清单是前端按节点类型
写死的特例,顺序、显隐、选中音色时顺手填资源号,全是那一处的规矩。

加一个来源 = 在 SOURCES 里加一个函数。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import t


class FieldOptionsError(ValueError):
    pass


@dataclass(frozen=True)
class OptionContext:
    workspace_id: str
    user_id: str | None
    #: `depends_on` 的那个字段现在的值;字段没有依赖时为空串。
    parent: str
    locale: str


Option = dict[str, str]
Source = Callable[[Session, OptionContext], list[Option]]



def _speech_engines(db: Session, ctx: OptionContext) -> list[Option]:
    """嗓子从哪来:克隆音色,或某个**已就绪**的引擎。

    没就绪的引擎(缺 Key、没装运行环境)不列 —— 列出来只会让人选中之后才失败。播客引擎不列:
    它一次产出整段对话,不是"念一句话"的那种。克隆这一项总在:没装好时它的音色清单是空的,
    选择本身仍然成立。
    """
    from app.domain.voices.engine_catalog import CLONE_ENGINE, PODCAST_ENGINE, describe_engines

    options: list[Option] = [{"value": CLONE_ENGINE, "label": t("wfSpeechEngineClone", ctx.locale)}]
    for engine in describe_engines(ctx.user_id):
        engine_id = str(engine["id"])
        if engine_id in (CLONE_ENGINE, PODCAST_ENGINE) or not engine.get("ready"):
            continue
        options.append({"value": engine_id, "label": t(str(engine["label"]), ctx.locale)})
    return options


def _speech_voices(db: Session, ctx: OptionContext) -> list[Option]:
    """这个引擎下能用的音色。克隆 → 工作区音色库;其余 → 那个引擎自己的目录。"""
    from app.db.models import Voice
    from app.domain.voices.engine_catalog import CLONE_ENGINE, list_engine_voices

    engine = ctx.parent.strip() or CLONE_ENGINE
    if engine == CLONE_ENGINE:
        rows = db.scalars(select(Voice).where(Voice.workspace_id == ctx.workspace_id).order_by(Voice.created_at))
        return [{"value": row.id, "label": row.name} for row in rows]
    return [
        {"value": str(item["value"]), "label": str(item.get("label") or item["value"])}
        for item in list_engine_voices(db, engine, user_id=ctx.user_id)
    ]


SOURCES: dict[str, Source] = {
    "speech_engines": _speech_engines,
    "speech_voices": _speech_voices,
}


def field_options(db: Session, source: str, ctx: OptionContext) -> list[Option]:
    handler = SOURCES.get(source)
    if handler is None:
        raise FieldOptionsError(f"未知的选项来源:{source}")
    return handler(db, ctx)
