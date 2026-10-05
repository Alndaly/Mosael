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

from app.core.i18n import MESSAGES, LocalizedError, t


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
    from app.domain.voices.engine_catalog import describe_engines
    from app.domain.voices.speech import CLONE_ENGINE, PODCAST_ENGINE

    options: list[Option] = [{"value": CLONE_ENGINE, "label": t("wfSpeechEngineClone", ctx.locale)}]
    for engine in describe_engines(db, ctx.user_id):
        engine_id = str(engine["id"])
        if engine_id in (CLONE_ENGINE, PODCAST_ENGINE) or not engine.get("ready"):
            continue
        options.append({"value": engine_id, "label": t(str(engine["label"]), ctx.locale)})
    return options


def _speech_voices(db: Session, ctx: OptionContext) -> list[Option]:
    """这个引擎下能用的音色。克隆 → 工作区音色库;其余 → 那个引擎自己的目录 —— 能复刻的引擎(CosyVoice)后面再接
    配音库里的嗓子(念它的远端副本,ADR 0037),名字前标「克隆」,和系统音色分得开。"""
    from app.db.models import Voice
    from app.domain.voices.engine_catalog import list_engine_voices
    from app.domain.voices.speech import CLONE_ENGINE

    engine = ctx.parent.strip() or CLONE_ENGINE
    if engine == CLONE_ENGINE:
        rows = db.scalars(select(Voice).where(Voice.workspace_id == ctx.workspace_id).order_by(Voice.created_at))
        return [{"value": row.id, "label": row.name} for row in rows]
    return [
        {
            "value": str(item["value"]),
            "label": t("wfSpeechVoiceCloned", ctx.locale, name=str(item.get("label") or item["value"]))
            if item.get("cloned")
            else str(item.get("label") or item["value"]),
        }
        for item in list_engine_voices(db, engine, user_id=ctx.user_id, workspace_id=ctx.workspace_id)
    ]


def _chat_connections(db: Session, ctx: OptionContext) -> list[Option]:
    """能拿来跑自动化对话的连接。**不是 llm 节点专属** —— 翻译节点选了 AI 引擎之后问的是
    同一个问题,而它此前只有一个自由文本框:要用户去别处把连接 id 抄过来。

    判据和界面上那份一致:启用的;订阅计划要连过;填 Key 的要有 base_url。
    """
    from app.domain.providers import credentials as provider_credentials
    from app.domain.providers.selection import list_enabled_connections

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
    from app.domain.providers import models as provider_models

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
        seen.setdefault(str(tool["package_id"]), str(tool["package_name"]))
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
    """这个工作区里**他能用**的发布账号:自己的,或主人共享出来的。

    此前列的是工作区里的全部账号 —— 同事的私有账号也在下拉里,选了之后运行时才被拒
    (publish.start_publish 查归属)。下拉和用的那一刻必须是同一个判据(sharing.usable_filter)。
    """
    from app.db.models import PublishAccount
    from app.domain import sharing

    rows = db.scalars(
        select(PublishAccount)
        .where(
            PublishAccount.workspace_id == ctx.workspace_id,
            sharing.usable_filter("publish_account", ctx.user_id, ctx.workspace_id),
        )
        .order_by(PublishAccount.created_at)
    )
    return [{"value": row.id, "label": row.name} for row in rows]


def _browser_profiles(db: Session, ctx: OptionContext) -> list[Option]:
    """「打开浏览器」池模式能借的档案:**他能用**的那些(自己的,或主人共享出来的)。

    此前这一格是个自由文本框,要用户去浏览器池里把档案 id 抄过来 —— 抄得到别人的,运行时
    才被拒(browser.usable_profile)。判据和浏览器池列表、用的那一刻是同一个。
    """
    from app.db.models import BrowserProfile
    from app.domain import sharing

    rows = db.scalars(
        select(BrowserProfile)
        .where(
            BrowserProfile.workspace_id == ctx.workspace_id,
            sharing.usable_filter("browser_profile", ctx.user_id, ctx.workspace_id),
        )
        .order_by(BrowserProfile.created_at.desc())
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
    from app.domain.scenes.operations import list_models

    return [{"value": model.id, "label": model.name} for model in list_models(db, ctx.workspace_id)]


def _scenes(db: Session, ctx: OptionContext) -> list[Option]:
    """这个工作区里的 3D 场景,按最近改过的排 —— 和「3D 场景」列表同一个顺序。

    此前「渲染白模参考」的场景一格是个文本框,要人去场景页把 id 抄过来。
    """
    from app.db.models import Scene3D

    rows = db.scalars(
        select(Scene3D).where(Scene3D.workspace_id == ctx.workspace_id).order_by(Scene3D.updated_at.desc())
    )
    return [{"value": row.id, "label": row.name} for row in rows]


def _scene_shots(db: Session, ctx: OptionContext) -> list[Option]:
    """`parent` 那个场景里的镜头,按场景里的顺序,显示镜头名。

    parent 说不出是哪个场景(还没挑、是一段 `{{…}}` 引用、不在这个工作区)时是空清单 ——
    不猜,也不把别的工作区的场景内容透出来。
    """
    from app.db.models import Scene3D

    scene_id = ctx.parent.strip()
    scene = db.get(Scene3D, scene_id) if scene_id else None
    if scene is None or scene.workspace_id != ctx.workspace_id:
        return []
    shots = [shot for shot in (scene.content or {}).get("shots") or [] if isinstance(shot, dict) and shot.get("id")]
    #: 重名的镜头(从 Blender 取回的相机常常同名)由 distinct_labels 统一带上一截 id。
    return [{"value": str(shot["id"]), "label": str(shot.get("name") or "").strip() or str(shot["id"])} for shot in shots]


def _projects(db: Session, ctx: OptionContext) -> list[Option]:
    """这个工作区里的项目,按最近改过的排(和项目列表同一个顺序)。"""
    from app.db.models import Project

    rows = db.scalars(
        select(Project).where(Project.workspace_id == ctx.workspace_id).order_by(Project.updated_at.desc())
    )
    return [{"value": row.id, "label": row.name} for row in rows]


def _sequences(db: Session, ctx: OptionContext) -> list[Option]:
    """这个工作区里的时间线,显示成「项目 / 时间线」—— 每个项目的时间线默认都叫同一个名字,
    不带项目名的话一列「主时间线」分不出谁是谁。"""
    from app.db.models import Project, Sequence

    rows = db.execute(
        select(Sequence.id, Sequence.name, Project.name)
        .join(Project, Project.id == Sequence.project_id)
        .where(Sequence.workspace_id == ctx.workspace_id)
        .order_by(Sequence.updated_at.desc())
    )
    return [{"value": sequence_id, "label": f"{project} / {name}"} for sequence_id, name, project in rows]


def _sequence_tracks(db: Session, ctx: OptionContext) -> list[Option]:
    """`parent` 那条时间线上的轨道,按轨道顺序,显示「名字 · 种类」(V1 · 视频)。

    parent 说不出是哪条时间线(还没挑、是上游的引用、不在这个工作区)时是空清单。
    """
    from app.db.models import Sequence, Track

    sequence_id = ctx.parent.strip()
    sequence = db.get(Sequence, sequence_id) if sequence_id else None
    if sequence is None or sequence.workspace_id != ctx.workspace_id:
        return []
    rows = db.scalars(select(Track).where(Track.sequence_id == sequence.id).order_by(Track.position))

    def kind(value: str) -> str:
        key = f"wfOpt_kind_{value}"
        return t(key, ctx.locale) if key in MESSAGES else value

    return [{"value": row.id, "label": f"{row.name} · {kind(row.kind)}"} for row in rows]


def _entities(db: Session, ctx: OptionContext, kind: str = "") -> list[Option]:
    """资产库里的人物 / 场景 / 道具(含变体),按最近改过的排。标签是「种类 · 名字」,变体带上母体的名字。

    `entities.<种类>` 只列那一种:字段声明点名种类(「选一个人物」),和选 3D 场景同一种下拉(ADR 0027 §3)。
    """
    from app.db.models import Entity

    stmt = select(Entity).where(Entity.workspace_id == ctx.workspace_id)
    if kind:
        stmt = stmt.where(Entity.kind == kind)
    rows = list(db.scalars(stmt.order_by(Entity.updated_at.desc())))
    names = {row.id: row.name for row in rows}

    def label(row: Entity) -> str:
        name = f"{names[row.parent_id]} · {row.name}" if row.parent_id in names else row.name
        return f"{t(f'entityKind_{row.kind}', ctx.locale)} · {name}"

    return [{"value": row.id, "label": label(row)} for row in rows]


def _entity_roles(db: Session, ctx: OptionContext) -> list[Option]:
    """参考图的角度 / 用途,按种类(`parent` 是种类:人物有表情,场景的角度是全景 / 反打 / 俯视)。没给种类列全部。
    名字在后端文案表里,按读的人的语言。"""
    from app.domain.entities.catalog import ROLES, ROLES_BY_KIND

    roles = ROLES_BY_KIND.get(ctx.parent, ROLES)
    return [{"value": role, "label": t(f"entityRole_{role}", ctx.locale)} for role in roles]


def _reference_image_models(db: Session, ctx: OptionContext) -> list[Option]:
    """收参考图的图片模型(资产格的「补全多角度」「生成表情」用):只看得到文字的模型画不出「同一个」。
    和生成页同一份清单(generation_options);留空时用的那一个标「默认」—— 和节点跑的时候同一个挑法
    (executors.entities.automatic_reference_model)。"""
    from app.domain.generation.resolution import generation_options
    from app.domain.workflows.executors.entities import automatic_reference_model, takes_reference_images

    options = generation_options(db, "image", user_id=ctx.user_id)
    automatic = automatic_reference_model(options)
    return [
        {"value": one["id"], "label": f"{one['label']} · {t('wfOpt_defaultModel', ctx.locale)}" if one is automatic else one["label"]}
        for one in options
        if takes_reference_images(one)
    ]


def _talking_models(mode: str) -> Source:
    """会说话照片 / 改口型的视频模型(描述符的 `modes` 声明了才列,ADR 0028)。留空用默认或第一个会的。"""

    def list_them(db: Session, ctx: OptionContext) -> list[Option]:
        from app.domain.workflows.executors.talking import talking_models

        return [{"value": one["id"], "label": one["label"]} for one in talking_models(db, mode, ctx.user_id)]

    return list_them


def _talking_resolutions(mode: str) -> Source:
    """挑中的那个说话照片 / 改口型模型有哪几档分辨率(描述符的 `resolutions`)。模型空着 = 节点会用的那一个(他的默认视频
    模型会这一种就是它,否则第一个会的),列它的档;第一项是模型的默认档。"""

    def list_them(db: Session, ctx: OptionContext) -> list[Option]:
        from app.domain.workflows.executors.talking import talking_models

        models = talking_models(db, mode, ctx.user_id)
        model = next((one for one in models if one["id"] == ctx.parent), None) if ctx.parent else (
            next((one for one in models if one.get("is_default")), None) or (models[0] if models else None))
        capabilities = (model or {}).get("capabilities") or {}
        offered = [str(one) for one in capabilities.get("resolutions") or []]
        default = str(capabilities.get("default_resolution") or "")
        ordered = [default, *(one for one in offered if one != default)] if default in offered else offered
        return [{"value": one, "label": one} for one in ordered]

    return list_them


def _capability_providers(capability_name: str) -> Source | None:
    """`providers.<能力>`:这项宿主能力此刻能用的提供方 —— 内置的,和这个人配好了的插件连接(ADR 0032 §3)。
    一个通用来源,不再每项能力写一个;缺配置、缺凭据、跑不起来的不列。认不出的能力回 None。"""
    from app.domain import capabilities

    capability = capabilities.get(capability_name)
    if capability is None:
        return None

    def options(db: Session, ctx: OptionContext) -> list[Option]:
        return [{"value": one.id, "label": one.name}
                for one in capabilities.providers(db, ctx.user_id, capability) if not one.missing]

    return options


def _automation_chat_models(db: Session, ctx: OptionContext) -> list[Option]:
    """能跑自动化对话的模型,**跨连接直接列模型** —— 和画板「让 AI 写」、设置页默认模型同一份清单
    (provider_models.models_for_capability)。值是 `<连接 id>:<模型>`,一次挑定两样:「先选连接再选模型」逼人先知道
    模型挂在哪条连接下,而那恰恰是他不关心的事。"""
    from app.domain.providers import models as provider_models

    return [
        {"value": f"{row.provider_profile_id}:{row.model_id}", "label": row.display_name or row.model_id}
        for row in provider_models.models_for_capability(db, "chat", ctx.user_id, surface="automation")
    ]


def split_chat_model(value: str) -> tuple[str, str]:
    """`automation_chat_models` 的值 → (连接 id, 模型)。空着就是两样都空(用默认)。"""
    profile, _, model = str(value or "").partition(":")
    return (profile, model) if model else ("", "")


SOURCES: dict[str, Source] = {
    "automation_chat_models": _automation_chat_models,
    "speech_video_models": _talking_models("speech-to-video"),
    "lipsync_models": _talking_models("video-lipsync"),
    "speech_video_resolutions": _talking_resolutions("speech-to-video"),
    "entities": _entities,
    "reference_image_models": _reference_image_models,
    "entities.character": lambda db, ctx: _entities(db, ctx, "character"),
    "entities.location": lambda db, ctx: _entities(db, ctx, "location"),
    "entities.prop": lambda db, ctx: _entities(db, ctx, "prop"),
    "entity_roles": _entity_roles,
    "scenes": _scenes,
    "scene_shots": _scene_shots,
    "projects": _projects,
    "sequences": _sequences,
    "sequence_tracks": _sequence_tracks,
    "scene_models": _scene_models,
    "speech_engines": _speech_engines,
    "speech_voices": _speech_voices,
    "chat_connections": _chat_connections,
    "chat_models": _chat_models,
    "plugin_packages": _plugin_packages,
    "plugin_tools": _plugin_tools,
    "plugin_instances": _plugin_instances,
    "publish_accounts": _publish_accounts,
    "browser_profiles": _browser_profiles,
    "callable_workflows": _callable_workflows,
}


def known_source(source: str) -> bool:
    """这个来源名认不认得:登记在 SOURCES 里的,或 `providers.<登记过的能力>`(ADR 0032)。"""
    from app.domain import capabilities
    from app.domain.capabilities import PROVIDERS_SOURCE

    if source in SOURCES:
        return True
    return source.startswith(PROVIDERS_SOURCE) and capabilities.get(source.removeprefix(PROVIDERS_SOURCE)) is not None


def field_options(db: Session, source: str, ctx: OptionContext) -> list[Option]:
    from app.domain.capabilities import PROVIDERS_SOURCE

    handler = SOURCES.get(source) or (
        _capability_providers(source.removeprefix(PROVIDERS_SOURCE)) if source.startswith(PROVIDERS_SOURCE) else None
    )
    if handler is None:
        raise FieldOptionsError("wfErr_unknownOptionSource", source=source)
    return distinct_labels(handler(db, ctx))


def distinct_labels(options: list[Option]) -> list[Option]:
    """同名的几项在名字后面带上 id,**所有来源一处做**。

    几个场景都叫「未命名场景」、两个项目同名,下拉里就是几行一模一样的字 —— 挑哪个全凭运气。短 id(镜头的
    `shot-2`)整个带上;长 id(32 位的那种)只截末 4 位(「未命名场景 · #3f9a」),万一这 4 位也撞了才用整个 id。
    名字唯一的不动。
    """
    counts: dict[str, int] = {}
    for option in options:
        counts[option["label"]] = counts.get(option["label"], 0) + 1
    tails = [option["value"][-4:] for option in options]
    out: list[Option] = []
    for option, tail in zip(options, tails):
        if counts[option["label"]] == 1:
            out.append(option)
            continue
        value = option["value"]
        suffix = value if len(value) <= 12 else (f"#{tail}" if tails.count(tail) == 1 else value)
        out.append({**option, "label": f"{option['label']} · {suffix}"})
    return out
