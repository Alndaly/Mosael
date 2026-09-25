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

from app.core.i18n import LocalizedError, t


class FieldOptionsError(LocalizedError, ValueError):
    """不认识的选项来源。带文案 key,按请求方的语言翻。"""


@dataclass(frozen=True)
class OptionContext:
    workspace_id: str
    user_id: str | None
    #: `depends_on` 的那个字段现在的值;字段没有依赖时为空串。
    parent: str
    locale: str
    #: 这个字段长在哪种节点上。插件节点的类型里带着包名(`plugin.<包>.<工具>`),
    #: 「用哪条连接」要靠它 —— 而那是**节点的身份**,不是某个字段的值。
    node_type: str = ""
    #: 正在编辑的这张工作流(可调用工作流的清单要把自己排掉)。新建、未保存时为空。
    workflow_id: str = ""


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
    for engine in describe_engines(db, ctx.user_id):
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


def _chat_connections(db: Session, ctx: OptionContext) -> list[Option]:
    """能拿来跑自动化对话的连接。**不是 llm 节点专属** —— 翻译节点选了 AI 引擎之后问的是
    同一个问题,而它此前只有一个自由文本框:要用户去别处把连接 id 抄过来。

    判据和界面上那份一致:启用的;订阅计划要连过;填 Key 的要有 base_url。
    """
    from app.domain import provider_credentials
    from app.domain.providers import list_enabled_connections

    options: list[Option] = []
    for profile in list_enabled_connections(db, owner_user_id=ctx.user_id):
        if profile.auth_type == "oauth":
            # 「连过没有」说的是当前用户自己那把钥匙 —— oauth_linked 是 API schema 上按用户
            # 算出来的展示字段,不是模型列;领域层直接读它会当场 AttributeError。
            credential = provider_credentials.get(db, profile.id, ctx.user_id) if ctx.user_id else None
            usable = bool(credential and credential.oauth_credential)
        else:
            usable = bool((profile.base_url or "").strip())
        if usable:
            options.append({"value": profile.id, "label": f"{profile.name}({profile.vendor})"})
    return options


def _chat_models(db: Session, ctx: OptionContext) -> list[Option]:
    """这条连接上**会对话**的模型。填不进去的死角由字段自己放行手填(allow_custom)——
    新模型上线往往早于目录更新。

    和模型选择器同一个判据(provider_models.models_for_capability):**他自己的**连接、启用、
    声明了 chat 能力、自动化这条执行通道走得通。此前直接列这条连接下全部启用的模型 ——
    同一端点上的生图/生视频模型也在下拉里,选中就是一次注定 400 的对话请求;也不核对连接
    归谁,拿别人的连接 id 当 parent 就能看到他配了哪些模型。
    """
    from app.domain import provider_models

    parent = ctx.parent.strip()
    if not parent:
        return []
    rows = sorted(
        (row for row in provider_models.models_for_capability(db, "chat", ctx.user_id, surface="automation")
         if row.provider_profile_id == parent),
        key=lambda row: row.model_id,
    )
    return [{"value": row.model_id, "label": row.display_name or row.model_id} for row in rows]


def _plugin_packages(db: Session, ctx: OptionContext) -> list[Option]:
    """接进来的插件包(按包,不按实例:同一个包的两次接入提供的是同一批工具)。"""
    from app.domain.plugins.tools import exposed

    seen: dict[str, str] = {}
    for tool in exposed(db, ctx.user_id):
        seen.setdefault(str(tool["package_id"]), str(tool["instance_name"]))
    return [{"value": package, "label": label} for package, label in seen.items()]


def _plugin_tools(db: Session, ctx: OptionContext) -> list[Option]:
    """这个包暴露出来的工具。"""
    from app.domain.plugins.tools import exposed

    package = ctx.parent.strip() or _package_of(ctx.node_type)
    names: dict[str, str] = {}
    for tool in exposed(db, ctx.user_id):
        if package and str(tool["package_id"]) != package:
            continue
        names.setdefault(str(tool["name"]), str(tool.get("label") or tool["name"]))
    return [{"value": name, "label": label} for name, label in names.items()]


def _plugin_instances(db: Session, ctx: OptionContext) -> list[Option]:
    """用哪一次接入(哪条连接)。插件节点的包名在**节点类型**里,通用 plugin_tool 节点的在
    它选中的那个包里 —— 两者都收在这一处,界面不必认识插件节点长什么样。"""
    from app.domain.plugins.tools import exposed

    package = _package_of(ctx.node_type) or ctx.parent.strip()
    seen: dict[str, str] = {}
    for tool in exposed(db, ctx.user_id):
        if package and str(tool["package_id"]) != package:
            continue
        seen.setdefault(str(tool["instance_id"]), str(tool["instance_name"]))
    return [{"value": instance, "label": label} for instance, label in seen.items()]


def _package_of(node_type: str) -> str:
    """`plugin.<包>.<工具>` → 包名;不是插件节点就是空串。"""
    from app.domain.plugins.nodes import parse_node_type

    parsed = parse_node_type(node_type)
    return parsed[0] if parsed else ""


def _publish_accounts(db: Session, ctx: OptionContext) -> list[Option]:
    """这个工作区里可用的发布账号。"""
    from app.db.models import PublishAccount

    rows = db.scalars(
        select(PublishAccount)
        .where(PublishAccount.workspace_id == ctx.workspace_id)
        .order_by(PublishAccount.created_at)
    )
    return [{"value": row.id, "label": row.name} for row in rows]


def _callable_workflows(db: Session, ctx: OptionContext) -> list[Option]:
    """能被调用的工作流。**把自己排掉** —— 直接自调是一定成环的那一种,没有理由摆在清单里
    (更深的环由运行时守卫拒绝)。"""
    from app.db.models import Workflow

    rows = db.scalars(
        select(Workflow)
        .where(Workflow.workspace_id == ctx.workspace_id)
        .order_by(Workflow.updated_at.desc())
    )
    return [{"value": row.id, "label": row.name} for row in rows if row.id != ctx.workflow_id]


def _scene_models(db: Session, ctx: OptionContext) -> list[Option]:
    """这个工作区里的 3D 模型 —— 能摆进白模布景的道具。

    模型归工作区(见 domain/scenes),所以这份清单不依赖任何一个场景:工作流每跑一次都新建
    场景,按场景列的话它永远是空的。
    """
    from app.domain.scenes import list_models

    return [{"value": model.id, "label": model.name} for model in list_models(db, ctx.workspace_id)]


SOURCES: dict[str, Source] = {
    "scene_models": _scene_models,
    "speech_engines": _speech_engines,
    "speech_voices": _speech_voices,
    "chat_connections": _chat_connections,
    "chat_models": _chat_models,
    "plugin_packages": _plugin_packages,
    "plugin_tools": _plugin_tools,
    "plugin_instances": _plugin_instances,
    "publish_accounts": _publish_accounts,
    "callable_workflows": _callable_workflows,
}


def field_options(db: Session, source: str, ctx: OptionContext) -> list[Option]:
    handler = SOURCES.get(source)
    if handler is None:
        raise FieldOptionsError("wfErr_unknownOptionSource", source=source)
    return handler(db, ctx)
