"""插件接口:包 → 实例 → 能力。

**包**是磁盘上的东西(扫描 / 卸载),**实例**是一次接入(配置 / 凭据 / 权限 / 启用),
**能力**是实例暴露出来的工具。三层各自一组端点,别处(智能体、工作流)只读 `/plugins/tools`。
"""

from __future__ import annotations

import re

import anyio.from_thread
from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import get_current_locale, render_message, tr, translate_fields
from app.api.deps import CurrentUser, DbSession, Tx
from app.api.schemas import (
    CapabilityTermOut,
    JobOut,
    ModelDetailOut,
    ModelDownloadRequest,
    ModelLibraryOut,
    ModelLocalNsfwOut,
    ModelLookupJobOut,
    ModelLookupRequest,
    ModelNsfwMarkRequest,
    ModelSavePreviewOut,
    ModelSavePreviewRequest,
    ModelNsfwOut,
    ModelNodeFoldersOut,
    ModelNodeFoldersRequest,
    ModelResolveOut,
    ModelResolveRequest,
    ModelSearchOut,
    ModelSearchRequest,
    PluginOAuthCode,
    PluginCapabilityUpdate,
    PluginCredentialOut,
    PluginCredentialUpdate,
    PluginInstallPreview,
    PluginInstallRequest,
    PluginInstanceCreate,
    PluginInstanceOut,
    PluginInstanceUpdate,
    PluginInvocationOut,
    PluginInvokeRequest,
    PluginMarketEntry,
    PluginMarketOut,
    PluginMarketTool,
    PluginPackageOut,
    PluginPermissionGrantOut,
    PluginPermissionGrantUpdate,
    PluginProvidedModelOut,
    PluginToolOut,
    WorkflowAnnotateOut,
    WorkflowAnnotateRequest,
    WorkflowAppOut,
    WorkflowCanvasMarksOut,
    WorkflowCanvasMarksRequest,
    WorkflowCanvasRequest,
    WorkflowContentOut,
    WorkflowCopyRequest,
    WorkflowFolderRenameRequest,
    WorkflowFolderRequest,
    WorkflowInstallNodesRequest,
    WorkflowLibraryImportOut,
    WorkflowLibraryImportRequest,
    WorkflowLibraryOut,
    WorkflowPathOut,
    WorkflowRenameRequest,
    WorkflowRebootOut,
    WorkflowRestoreRequest,
    WorkflowCanvasRunRequest,
    WorkflowLibrarySaveRequest,
    WorkflowTrashRequest,
)
from app.core.config import settings
from app.domain.effects import EFFECTS
from app.domain.permissions import ensure_deployment_admin
from app.db.models import Job, PluginInstance, PluginInvocation, PluginMarketHold, PluginPackage, User
from app.api.schemas.generation import GenerationCreateResponse, GenerationJobOut
from app.ai.runtime import nsfw_models
from app.ai.runtime.errors import RuntimeSetupError
from app.domain import model_library
from app.domain import model_nsfw_local
from app.domain import workflow_library
from app.domain.generation.operations import GenerationDomainError
from app.domain.plugins import PluginDomainError
from app.domain.plugins.runtime import PluginRuntimeError
from app.domain.plugins import bundled
from app.domain.plugins import host_capabilities
from app.domain.plugins import instances as inst
from app.domain.plugins import package_sources
from app.domain.plugins import install as installer
from app.domain.plugins import oauth as plugin_oauth
from app.domain.plugins import packages as pkg
from app.domain.plugins import registry as market
from app.domain.plugins import tools as tools_domain
from app.domain.plugins import updates
from app.domain.plugins import use_cases as plugin_use_cases
from app.domain.plugins.manifest import GENERATION, manifest_of, text_of, web_url

router = APIRouter(tags=["plugins"])


def _fail(exc: PluginDomainError, status: int = 422) -> HTTPException:
    return HTTPException(status_code=status, detail=str(exc))


# --- 包 -----------------------------------------------------------------

@router.post("/plugins/scan", response_model=list[PluginPackageOut])
def scan_packages(db: DbSession, user: CurrentUser) -> list[dict]:
    ensure_deployment_admin(db, user)
    try:
        installer.raise_problems(installer.sync(db, settings.plugins_dir, owner_user_id=user.id))
    except PluginDomainError as exc:
        raise _fail(exc) from exc
    return _packages(db, user)


@router.get("/plugins/capabilities", response_model=list[CapabilityTermOut])
def list_capability_terms(user: CurrentUser) -> list[dict]:
    """插件能替 Mosael 做的那几类事(清单里的 `provides`):叫什么、装上之后用在哪。插件市场按它筛,插件页照它说。"""
    from app.domain import capabilities

    return capabilities.vocabulary()


@router.get("/plugins/market", response_model=PluginMarketOut)
def browse_market(db: DbSession, user: CurrentUser) -> PluginMarketOut:
    """市场里有什么。**要管理员** —— 看到的下一步就是装,而装是往这台机器上放代码。

    **随应用内置的插件总在里面**,不管远端索引有没有它、拉不拉得到:它就装在这台机器上,
    条目由本地那份清单生成(版本也是本地的)。远端若也列了它,以本地为准 —— 内置插件的新版
    跟着应用发,远端的版本号不该在这里长出一个「更新」。
    """
    ensure_deployment_admin(db, user)
    installed = {row.id: row for row in db.scalars(select(PluginPackage))}
    shipped = [one for one in bundled.plugins() if one.id in installed]
    index_error = ""
    try:
        remote = market.fetch_index(market.index_url(db))
    except PluginDomainError as exc:
        remote, index_error = [], str(exc)
    local_ids = {one.id for one in shipped}
    entries = [market.bundled_entry(manifest_of(installed[one.id])) for one in shipped] + [
        entry for entry in remote if entry["id"] not in local_ids
    ]
    holds = updates.holds(db)
    return PluginMarketOut(
        plugins=[_market_entry(entry, installed, holds) for entry in entries],
        index_error=index_error,
    )


def _market_entry(entry: dict, installed: dict[str, PluginPackage], holds: dict[str, PluginMarketHold]) -> PluginMarketEntry:
    package = installed.get(entry["id"])
    update = updates.state_of(entry, package, holds.get(entry["id"]))
    return PluginMarketEntry(
        **{key: str(entry.get(key, "")) for key in ("id", "version", "author", "homepage", "download", "sha256")},
        author_url=web_url(entry.get("author_url")),
        #: docs 在索引里也可以按语言分,和名字、简介一样在这儿定语言。
        docs=web_url(text_of(entry.get("docs"))),
        #: 索引里的名字和简介照搬清单,而清单里它们可以是按语言分的对象 —— 在这儿定语言。
        name=text_of(entry.get("name")),
        summary=text_of(entry.get("summary")),
        description=text_of(entry.get("description")),
        permissions=[p for p in (entry.get("permissions") or []) if isinstance(p, str)],
        runtime=str(entry.get("runtime") or "process"),
        provides=[p for p in (entry.get("provides") or []) if isinstance(p, str)],
        tools=[
            PluginMarketTool(
                name=str(tool["name"]),
                label=text_of(tool.get("label")),
                description=text_of(tool.get("description")),
                #: 索引里写了什么就是什么;不认识的值当没写(界面不标),不在这里替它猜。
                effects=str(tool.get("effects")) if tool.get("effects") in EFFECTS else "",
            )
            for tool in (entry.get("tools") or [])
            if isinstance(tool, dict) and tool.get("name")
        ],
        installed=package is not None,
        installed_version=package.version if package else "",
        update_available=update.available,
        update_unreleased=update.unreleased,
        bundled=entry.get("bundled") is True,
    )


@router.post("/plugins/install/preview", response_model=PluginInstallPreview)
def preview_install(body: PluginInstallRequest, db: DbSession, user: CurrentUser) -> PluginInstallPreview:
    """下下来读一遍清单就扔 —— **让用户在装之前看见它要什么权限**。

    权限清单写在清单里,而清单在包里面,不下下来看不到。少了这一步,「安装」就是一个
    什么都不说的按钮,而它做的事是往这台机器上放一份会被执行的代码。
    """
    ensure_deployment_admin(db, user)
    url = body.url.strip()
    try:
        raw = market.read_manifest(market.download_archive(url, sha256=body.sha256))
    except PluginDomainError as exc:
        raise _fail(exc) from exc
    #: 从市场点「更新」:包里实际那一版不比装着的新,就不给确认卡(那张卡会说「更新」),
    #: 而是告诉界面「新版本还没发布」,并记下来让市场先别再说「有新版」(见 domain/plugins/updates)。
    unreleased = updates.not_released(db, raw, advertised_version=body.advertised_version, download=url)
    if unreleased:
        db.commit()
    existing = db.get(PluginPackage, str(raw.get("id") or ""))
    declared = (raw.get("tools") or {}).get("declare") if isinstance(raw.get("tools"), dict) else []
    return PluginInstallPreview(
        id=str(raw.get("id") or ""),
        name=text_of(raw.get("name")),
        version=str(raw.get("version") or ""),
        summary=text_of(raw.get("summary")),
        description=text_of((raw.get("toolsets") or [{}])[0].get("description")) if raw.get("toolsets") else "",
        permissions=[p for p in (raw.get("permissions") or []) if isinstance(p, str)],
        tools=[str(t.get("name")) for t in (declared or []) if isinstance(t, dict) and t.get("name")],
        #: 只取这一个字段,不跑整份 parse —— 这份清单还没装上,它可能是畸形的,而
        #: 「预览」正是用来看清楚它的那一步,不该被它自己打成 500。
        homepage=web_url(raw.get("homepage")),
        author_name=text_of((raw.get("author") or {}).get("name")) if isinstance(raw.get("author"), dict) else "",
        author_url=web_url((raw.get("author") or {}).get("url")) if isinstance(raw.get("author"), dict) else "",
        docs=web_url(text_of(raw.get("docs"))),
        installed=existing is not None,
        installed_version=existing.version if existing else "",
        update_unreleased=unreleased,
    )


@router.post("/plugins/install", response_model=list[PluginPackageOut])
def install_from_url(body: PluginInstallRequest, db: DbSession, user: CurrentUser) -> list[dict]:
    """下下来装上,然后照常扫描一遍(建默认实例、对齐字段)。

    **从市场更新时先认一眼包里的版本**:预览和安装之间索引可能变了,而装回同一版再报「已更新」
    正是「明明装好了还显示更新」的来源。不比装着的新就不装,回 409 说清「还没发布」。
    """
    ensure_deployment_admin(db, user)
    url = body.url.strip()
    try:
        data = market.download_archive(url, sha256=body.sha256)
        raw = market.read_manifest(data)
        if updates.not_released(db, raw, advertised_version=body.advertised_version, download=url):
            db.commit()
            raise _fail(PluginDomainError("pluginErr_updateNotReleased"), status=409)
        market.install_archive(data, settings.plugins_dir, overwrite=body.overwrite)
        installer.sync(db, settings.plugins_dir, owner_user_id=user.id)
        updates.clear(db, str(raw.get("id") or ""))
        db.commit()
    except PluginDomainError as exc:
        raise _fail(exc) from exc
    return _packages(db, user)


@router.get("/plugins/dir")
def plugins_directory(user: CurrentUser) -> dict[str, str]:
    """插件目录的**真实绝对路径**,给前端的空态引导用。

    这条路径曾经写死在前端文案里(`~/.mosael/plugins/`)。那是 POSIX 写法:Windows 上
    `~/` 对用户没有任何意义,照着找是找不到的。路径由谁算就由谁报。
    """
    return {"path": str(settings.plugins_dir)}


@router.get("/plugins", response_model=list[PluginPackageOut])
def list_packages(db: DbSession, user: CurrentUser) -> list[dict]:
    return _packages(db, user)


def my_instance(db: DbSession, instance_id: str, user: CurrentUser) -> PluginInstance:
    """**我自己接的**那个,不是就 404。

    接入归人(见 db.models.PluginInstance)。"别人接的"和"不存在"对他是同一件事 —— 回 403 等于
    告诉他这个 id 有效。归属判定只此一处:每个路由各写一遍的话,漏掉任何一处都不会报错,
    只会让那条路径能读到别人的第三方凭据。
    """
    instance = db.get(PluginInstance, instance_id)
    if instance is None or instance.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail=tr("routeErr_pluginConnectionNotFound"))
    return instance


def _my_instance_ids(db: DbSession, user: CurrentUser) -> list[str]:
    return list(db.scalars(select(PluginInstance.id).where(PluginInstance.owner_user_id == user.id)))


def _packages(db: DbSession, user: CurrentUser) -> list[dict]:
    """装了哪些包 + **我自己**接的那些实例。

    包是这台机器的事实,人人看得到(否则他不知道有什么可接);实例是他自己的接入,别人的一个
    都不该出现 —— 此前这里不做过滤,新账号一进插件页就看到管理员接好的一排。
    """
    out: list[dict] = []
    shipped = {one.id for one in bundled.plugins()}
    for package in db.scalars(select(PluginPackage).order_by(PluginPackage.name)):
        manifest = manifest_of(package)
        out.append(
            {
                "id": package.id,
                #: 名字从清单现取,不取库里那一列 —— 那一列是装的时候定的,装的人是什么语言
                #: 就一直是什么语言;清单里若写了多语言,这里才跟得上看的人。
                "name": manifest.name,
                "version": package.version,
                "summary": manifest.summary,
                "description": manifest.description,
                #: 和市场条目同一个形状、同一个算法(registry.market_tools):「关于」里的工具和市场里的一致。
                "tools": market.market_tools(manifest),
                "kind": manifest.runtime.kind,
                "multiple": manifest.multiple,
                "permissions": manifest.permissions,
                "homepage": manifest.homepage,
                "author_name": manifest.author.name,
                "author_url": manifest.author.url,
                "docs": manifest.docs,
                "config_fields": [_field(f) for f in manifest.config],
                "summary_field": _summary_field(manifest),
                "credential_fields": [_field(f) for f in manifest.credentials],
                #: 声明了 OAuth 就给一个「去授权」的入口,不必手抄令牌(见 domain/plugins/oauth)。
                #: 声明不全的当没声明 —— 半个声明会长出一个点了必然失败的按钮。
                "oauth": (
                    {"fills": [one.key for one in plugin_oauth.fills(manifest.oauth, manifest.credentials)]}
                    if manifest.oauth is not None
                    else None
                ),
                "provides": manifest.provides,
                "bundled": package.id in shipped,
                "instances": [
                    _instance(db, i)
                    for i in pkg.instances_of(db, package.id)
                    if i.owner_user_id == user.id
                ],
            }
        )
    return out


_TEMPLATE_KEY = re.compile(r"\{([A-Za-z0-9_]+)(?::label)?\}")


def _summary_field(manifest) -> str:
    """插件页上**收起的连接**那一行摆哪一项配置(「关键地址」):名字模板里引用的第一个配置项(ComfyUI 的
    `{server_url}`、TikHub 的 `{platform:label}`);没写模板就是第一个必填的文本配置项;都没有就是空串(不摆)。"""
    config = {field.key: field for field in manifest.config}
    for key in _TEMPLATE_KEY.findall(manifest.name_template or ""):
        if key in config:
            return key
    return next((field.key for field in manifest.config if field.required and field.type == "string"), "")


def _field(spec) -> dict:
    return {
        "key": spec.key,
        "label": spec.label,
        "type": spec.type,
        "help": spec.help,
        "required": spec.required,
        "secret": spec.secret,
        "options": spec.options,
        "default": spec.default,
        "multiline": spec.multiline,
        "language": spec.language,
    }


def _instance(db: DbSession, instance) -> dict:
    chosen = inst.exposed_tools(db, instance.id)
    tools = tools_domain.all_tools(db, instance)
    return {
        "id": instance.id,
        "package_id": instance.package_id,
        "name": instance.name,
        "enabled": instance.enabled,
        "config": instance.config or {},
        "blocked_reason": inst.blocked_reason(db, instance),
        "pending_permissions": inst.pending_permissions(db, instance),
        "permissions_added": inst.permissions_added(db, instance),
        "authorization": inst.authorization_state(db, instance),
        # internal 的工具只给宿主适配层用,勾选列表里不出现 —— 勾上也不会暴露,列出来只会让人以为能。认领调用类能力的
        # (MinerU 的解析)是普通工具,在这张表里,带着能力和「也用在」(ADR 0033)。
        "tools": [{**tool, "exposed": tool["name"] in chosen, "form": _tool_form(tool), "used_by": _used_by(tool["provides"])}
                  for tool in tools if not tool["internal"]],
        "capability_status": {
            capability: _capability_status(status)
            for capability, status in (instance.capability_status or {}).items()
            if isinstance(status, dict)
        },
        "network": {"mode": instance.network_mode, "proxy_url": instance.proxy_url},
        "package_sources": package_sources.describe(inst.manifest_for(db, instance).package_sources,
                                                    instance.package_sources),
    }


def _used_by(provides: list[str]) -> list[dict]:
    from app.domain import capabilities

    return [{"capability": capability, **use} for capability in provides for use in capabilities.used_by(capability)]


def _tool_form(tool: dict) -> dict:
    """插件页「试一下」那张表单的字段 —— **和这个工具在工作流里当节点时是同一份声明**(名字、素材选择器、
    下拉、数字框、高级那一档),前端用同一个表单组件渲染。选连接那一格不要:试跑就是在这个连接上。"""
    from app.domain.plugins.nodes import node_meta
    from app.domain.workflows.node_catalog import translated_spec, with_data_type

    locale = get_current_locale()
    config = node_meta(tool).get("config") or {}
    return {
        key: translated_spec(key, with_data_type(key, spec), locale)
        for key, spec in config.items()
        if key != "instance_id" and isinstance(spec, dict)
    }


def _capability_status(status: dict) -> dict:
    """落库的那一份(失败原因存的是文案 key + 参数,见 jobs.blame)→ 按看的人的语言说出来。"""
    key = str(status.get("error_key") or "")
    error = render_message(key, get_current_locale(), status.get("error_params") or {}) if key else str(
        status.get("error") or ""
    )
    return {
        "models": status.get("models"),
        "tools": status.get("tools"),
        "refreshed_at": status.get("refreshed_at"),
        "error": error,
    }


# --- 实例 ---------------------------------------------------------------

@router.post("/plugins/{package_id}/instances", response_model=PluginInstanceOut)
def create_instance(package_id: str, body: PluginInstanceCreate, db: DbSession, user: CurrentUser) -> dict:
    """接一个**我自己的**。不要求部署管理员:他自己的账号、他自己的额度。

    没有归属判定可做(还没有这个接入)—— 建出来的就归他,这一行本身就是那道闸。
    """
    try:
        instance = inst.create(db, package_id, body.config, body.name, owner_user_id=user.id)
    except PluginDomainError as exc:
        raise _fail(exc) from exc
    return _instance(db, instance)


@router.patch("/plugins/instances/{instance_id}", response_model=PluginInstanceOut)
def update_instance(instance_id: str, body: PluginInstanceUpdate, db: Tx, user: CurrentUser) -> dict:
    try:
        instance = my_instance(db, instance_id, user)
        # 一次保存可能同时改名、改配置、启停:逐个改、**最后统一通知一次**替宿主做事的那一侧 ——
        # 否则一个 ComfyUI 实例的一次保存会把服务器上的工作流清单拉三遍。
        if body.name is not None:
            inst.rename(db, instance, body.name, notify=False)
        if body.config is not None:
            inst.set_config(db, instance, body.config, notify=False)
        if body.enabled is not None:
            inst.set_enabled(db, instance, body.enabled, notify=False)
        if body.network is not None:
            inst.set_network(db, instance, body.network.mode, body.network.proxy_url, notify=False)
        if body.package_sources is not None:
            inst.set_package_sources(db, instance, body.package_sources)
        host_capabilities.notify(
            db, instance, refresh=any(one is not None for one in (body.config, body.enabled, body.network))
        )
    except PluginDomainError as exc:
        raise _fail(exc) from exc
    return _instance(db, instance)


@router.delete("/plugins/instances/{instance_id}", status_code=204)
def delete_instance(instance_id: str, db: DbSession, user: CurrentUser) -> None:
    try:
        db.delete(my_instance(db, instance_id, user))
        db.commit()
        # 模型库记着的预览图(内存里的地址、磁盘上的图)跟着连接走。
        model_library.drop_cache(instance_id)
    except PluginDomainError as exc:
        raise _fail(exc, 404) from exc


@router.post("/plugins/instances/{instance_id}/refresh", response_model=PluginInstanceOut)
def refresh_instance_tools(instance_id: str, db: DbSession, user: CurrentUser) -> dict:
    """重新向 MCP 服务要工具清单。进程类实例直接原样返回。"""
    try:
        instance = tools_domain.refresh_tools(db, my_instance(db, instance_id, user))
    except PluginDomainError as exc:
        raise _fail(exc) from exc
    return _instance(db, instance)


@router.get("/plugins/instances/{instance_id}/models", response_model=list[PluginProvidedModelOut])
def list_instance_models(instance_id: str, db: DbSession, user: CurrentUser) -> list[dict]:
    """这个连接**替宿主提供的模型**(生成能力;见 ADR 0020)。读的是缓存的那一份,不现问插件 ——
    要最新的走 `/refresh`。不提供生成的连接回空列表。"""
    try:
        instance = my_instance(db, instance_id, user)
    except PluginDomainError as exc:
        raise _fail(exc, 404) from exc
    return host_capabilities.listing(db, instance, GENERATION) or []


# --- 模型库(ADR 0034) ----------------------------------------------------
#
# 认领 `model_library` 的连接上有哪些模型文件:列出、看详情、取预览图、解析链接、下载。插件那一头说的错(连不上、
# 链接认不出)原话交回(422);不提供模型库的连接也是 422,说清楚是哪一个。


def _model_library_failed(exc: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


_MODEL_LIBRARY_ERRORS = (model_library.ModelLibraryError, PluginDomainError, PluginRuntimeError)


@router.get("/plugins/instances/{instance_id}/model-library", response_model=ModelLibraryOut)
def get_model_library(instance_id: str, db: DbSession, user: CurrentUser, pick: str = "safest") -> dict:
    """现问插件:这个连接上的全部模型文件、工作流缺的模型、下载走哪条路,外加最近的下载任务。`pick`:那台服务器上没有
    预览图、用别处(Civitai)的示例图时挑哪一张 —— `safest` 分级最低的,`cover` 作者排在最前的(界面按「NSFW 预览」
    那组设置要);预览图从哪来、NSFW 的判断都照它。"""
    instance = my_instance(db, instance_id, user)
    try:
        return model_library.library(db, instance, pick)
    except _MODEL_LIBRARY_ERRORS as exc:
        raise _model_library_failed(exc) from exc


def _model_image(
    db: Session, user: User, request: Request, instance_id: str, folder: str, name: str, *, thumbnail: bool,
    pick: str = "safest",
) -> Response:
    """预览图和缩略图两个端点的身子。读库(认连接、找这张图在哪)在前头一次读完,**随后交还数据库连接**:缓存里没有时
    要排队等那台服务器(见 model_library.PreviewSource),不攥着连接等。排到去取时浏览器已经掐了这个请求(卡片滚出去、
    弹窗关了)就不取 —— 端点是同步的、在线程池里跑,回事件循环问一句。"""
    instance = my_instance(db, instance_id, user)
    try:
        source = model_library.preview_source(db, instance, folder, name, pick)
    except _MODEL_LIBRARY_ERRORS as exc:
        raise _model_library_failed(exc) from exc
    db.close()
    if source is not None:
        def wanted() -> bool:
            return not anyio.from_thread.run(request.is_disconnected)

        found = source.thumbnail(wanted) if thumbnail else source.original(wanted)
        if found is not None:
            data, kind = found
            return Response(content=data, media_type=kind, headers={"Cache-Control": "private, max-age=3600"})
    raise HTTPException(status_code=404, detail=tr("routeErr_modelPreviewNotFound"))


@router.get("/plugins/instances/{instance_id}/model-library/preview")
def get_model_preview(
    instance_id: str, folder: str, name: str, request: Request, db: DbSession, user: CurrentUser, pick: str = "safest"
) -> Response:
    """一个模型文件的预览图原图(详情页的大图)。宿主按插件给的地址取回、记在磁盘上;没有就 404(界面换成按目录分的
    占位)。`<img>` 带不了请求头,凭据走 `?token=`(和素材的图同一条旁路)。"""
    return _model_image(db, user, request, instance_id, folder, name, thumbnail=False, pick=pick)


@router.get("/plugins/instances/{instance_id}/model-library/thumbnail")
def get_model_thumbnail(
    instance_id: str, folder: str, name: str, request: Request, db: DbSession, user: CurrentUser, pick: str = "safest"
) -> Response:
    """预览图的缩略图(长边不超过 512 的 WebP):模型库的卡片和列表、生成表单里选模型的下拉用它,一屏几十张不解原图。
    第一次要时由原图缩一次、记在原图旁边;没有预览图就 404。凭据同上走 `?token=`。"""
    return _model_image(db, user, request, instance_id, folder, name, thumbnail=True, pick=pick)


@router.get("/plugins/instances/{instance_id}/model-library/detail", response_model=ModelDetailOut)
def get_model_detail(instance_id: str, folder: str, name: str, db: DbSession, user: CurrentUser) -> dict:
    instance = my_instance(db, instance_id, user)
    try:
        return model_library.detail(db, instance, folder, name)
    except _MODEL_LIBRARY_ERRORS as exc:
        raise _model_library_failed(exc) from exc


@router.post("/plugins/instances/{instance_id}/model-library/resolve", response_model=ModelResolveOut)
def resolve_model_link(instance_id: str, body: ModelResolveRequest, db: DbSession, user: CurrentUser) -> dict:
    """一个链接(HuggingFace 文件、Civitai 页面或下载链接、ModelScope 的模型页或文件、别的直链)指的是什么:文件名、大小、
    建议的目录、同名文件在不在。"""
    instance = my_instance(db, instance_id, user)
    try:
        return model_library.resolve(db, instance, body.url)
    except _MODEL_LIBRARY_ERRORS as exc:
        raise _model_library_failed(exc) from exc


@router.post("/plugins/instances/{instance_id}/model-library/search", response_model=ModelSearchOut)
def search_model_sources(instance_id: str, body: ModelSearchRequest, db: DbSession, user: CurrentUser) -> dict:
    """按文件名去模型站(HuggingFace、ModelScope、Civitai)上找下载地址:工作流里只写了文件名的模型。同名的候选在前;
    一个站搜不了只进 `failed`,别的站照常交回。每个候选的 `url` 交给 `/resolve` 正好解析到那个文件。"""
    instance = my_instance(db, instance_id, user)
    try:
        return model_library.search_sources(db, instance, body.filename, body.folder)
    except _MODEL_LIBRARY_ERRORS as exc:
        raise _model_library_failed(exc) from exc


@router.post("/plugins/instances/{instance_id}/model-library/downloads", response_model=JobOut)
def start_model_download(instance_id: str, body: ModelDownloadRequest, db: Tx, user: CurrentUser) -> Job:
    """把一个模型下到这个连接的那台服务器上:返回后台任务(进度、取消都在任务上)。不覆盖已有文件 —— 那由插件在写入时再查一遍。"""
    instance = my_instance(db, instance_id, user)
    try:
        return model_library.start_download(
            db, user, instance, workspace_id=body.workspace_id, url=body.url, folder=body.folder, filename=body.filename
        )
    except _MODEL_LIBRARY_ERRORS as exc:
        raise _model_library_failed(exc) from exc


@router.post("/plugins/instances/{instance_id}/model-library/lookups", response_model=JobOut)
def start_model_lookup(instance_id: str, body: ModelLookupRequest, db: Tx, user: CurrentUser) -> Job:
    """在 Civitai 上找这几个文件(不给 `files` 是这台服务器上没有预览图的全部),`save` 时找到的顺手存成预览图:一个后台
    任务(按哈希找要那台机器把整个文件读一遍)。"""
    instance = my_instance(db, instance_id, user)
    try:
        return model_library.start_lookup(
            db, user, instance, workspace_id=body.workspace_id,
            files=[one.model_dump() for one in body.files] if body.files is not None else None,
            save=body.save, pick=body.pick, refresh=body.refresh,
        )
    except _MODEL_LIBRARY_ERRORS as exc:
        raise _model_library_failed(exc) from exc


@router.get("/plugins/instances/{instance_id}/model-library/lookups/{job_id}", response_model=ModelLookupJobOut)
def get_model_lookup(instance_id: str, job_id: str, db: DbSession, user: CurrentUser) -> dict:
    """一个找、补预览图任务现在怎样:任务本身,做完了带上它交回的 —— 对上的那几条现在的样子(`found`),界面当场改模型库里
    那几条,不等整份重列。"""
    instance = my_instance(db, instance_id, user)
    try:
        return model_library.lookup_job(db, user, instance, job_id)
    except _MODEL_LIBRARY_ERRORS as exc:
        raise _model_library_failed(exc) from exc


@router.post("/plugins/instances/{instance_id}/model-library/save-preview", response_model=ModelSavePreviewOut)
def save_model_preview(instance_id: str, body: ModelSavePreviewRequest, db: DbSession, user: CurrentUser) -> dict:
    """把 Mosael 里显示的那张别处的示例图存成这个文件在那台服务器上的预览图(写在模型旁边)。那台服务器上已经有预览图的
    不写;按文件名对上的要 `confirmed`。"""
    instance = my_instance(db, instance_id, user)
    try:
        return model_library.save_preview(db, instance, body.folder, body.name, pick=body.pick, confirmed=body.confirmed)
    except _MODEL_LIBRARY_ERRORS as exc:
        raise _model_library_failed(exc) from exc


@router.put("/plugins/instances/{instance_id}/model-library/nsfw", response_model=ModelNsfwOut)
def mark_model_nsfw(instance_id: str, body: ModelNsfwMarkRequest, db: Tx, user: CurrentUser) -> dict:
    """手动标一个模型文件的预览图是不是 NSFW(ADR 0038 §9),`nsfw: null` 去掉标记。回合成之后的判断(手动的压过
    自动的)。只记在 Mosael 这边,不改那台服务器。"""
    instance = my_instance(db, instance_id, user)
    try:
        return model_library.mark_nsfw(db, user, instance, body.folder, body.name, body.nsfw)
    except _MODEL_LIBRARY_ERRORS as exc:
        raise _model_library_failed(exc) from exc


def _local_nsfw() -> dict:
    row = {**nsfw_models.status(), **model_nsfw_local.status()}
    return translate_fields(row, ("message",), get_current_locale())


@router.get("/model-library/local-nsfw", response_model=ModelLocalNsfwOut)
def get_local_nsfw(user: CurrentUser) -> dict:
    """本机识别 NSFW 预览图(ADR 0038 §9):权重下了没有,识别排着几张、算过几张。全部连接共用一份。"""
    return _local_nsfw()


@router.post("/model-library/local-nsfw/install", response_model=ModelLocalNsfwOut)
def install_local_nsfw(db: DbSession, user: CurrentUser) -> dict:
    """下载本机识别的权重(22.4 MB,钉死版本、校验 SHA-256)。往后端主机上放东西是部署级动作:只给部署管理员。"""
    ensure_deployment_admin(db, user)
    try:
        nsfw_models.start_install()
    except RuntimeSetupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _local_nsfw()


@router.post("/plugins/instances/{instance_id}/model-library/node-folders", response_model=ModelNodeFoldersOut)
def get_model_node_folders(instance_id: str, body: ModelNodeFoldersRequest, db: DbSession, user: CurrentUser) -> dict:
    """工作台的「模型库」面板(ADR 0038 §6):画布上选中的节点那几格各选的是哪个模型目录的文件。只查表,不改那台机器。"""
    instance = my_instance(db, instance_id, user)
    try:
        return model_library.node_folders(db, instance, [one.model_dump() for one in body.nodes])
    except _MODEL_LIBRARY_ERRORS as exc:
        raise _model_library_failed(exc) from exc


# 认领 `workflow_library` 的连接上存着哪些工作流(ADR 0035):列出、取原文、复制、改名、挪进 / 挪出回收目录、文件夹。改的是那台
# 服务器上的文件:撞名回 409(带一个建议名,不覆盖);插件那一头说的错(连不上、它自己的报错)和路径不对回 422,原话交给界面。

def _workflow_library_failed(exc: Exception) -> HTTPException:
    if isinstance(exc, workflow_library.WorkflowConflict):
        return HTTPException(status_code=409, detail={"code": "exists", "message": str(exc), "suggestion": exc.suggestion})
    if isinstance(exc, workflow_library.WorkflowFolderNotEmpty):
        return HTTPException(status_code=409, detail={"code": "not_empty", "message": str(exc), "count": exc.count})
    if isinstance(exc, workflow_library.WorkflowStale):
        return HTTPException(status_code=409, detail={"code": "stale", "message": str(exc), "modified": exc.modified})
    return HTTPException(status_code=422, detail=str(exc))


_WORKFLOW_LIBRARY_ERRORS = (workflow_library.WorkflowLibraryError, PluginDomainError, PluginRuntimeError)


@router.get("/plugins/instances/{instance_id}/workflow-library", response_model=WorkflowLibraryOut)
def get_workflow_library(instance_id: str, db: DbSession, user: CurrentUser, workspace_id: str = "") -> dict:
    """现问插件:这个连接上存着的全部工作流(图摘要、识别出的输入 / 参数 / 输出、用到的模型、缺什么)、回收目录里的;
    给了 `workspace_id` 就带上这个工作区里最近一次用它生成的产出。"""
    instance = my_instance(db, instance_id, user)
    try:
        return workflow_library.library(db, user, instance, workspace_id=workspace_id)
    except _WORKFLOW_LIBRARY_ERRORS as exc:
        raise _workflow_library_failed(exc) from exc


@router.get("/plugins/instances/{instance_id}/workflow-library/content", response_model=WorkflowContentOut)
def get_workflow_content(instance_id: str, path: str, db: DbSession, user: CurrentUser) -> dict:
    """一张工作流的原文(导出成 JSON)。"""
    instance = my_instance(db, instance_id, user)
    try:
        return workflow_library.content(db, instance, path)
    except _WORKFLOW_LIBRARY_ERRORS as exc:
        raise _workflow_library_failed(exc) from exc


@router.get("/plugins/instances/{instance_id}/workflow-library/app", response_model=WorkflowAppOut)
def get_workflow_app(instance_id: str, path: str, db: DbSession, user: CurrentUser) -> dict:
    """一张工作流的应用表单(ADR 0038):全部能填的项、交回结果的输出节点、文件里的标记、读到时的改动时间。"""
    instance = my_instance(db, instance_id, user)
    try:
        return workflow_library.app_form(db, instance, path)
    except _WORKFLOW_LIBRARY_ERRORS as exc:
        raise _workflow_library_failed(exc) from exc


@router.post("/plugins/instances/{instance_id}/workflow-library/annotate", response_model=WorkflowAnnotateOut)
def annotate_workflow(instance_id: str, body: WorkflowAnnotateRequest, db: Tx, user: CurrentUser) -> dict:
    """改那台服务器上一张工作流的应用表单和结果标记:只改 `mosael` 那几处,覆盖写(界面上确认过)。那张在读到之后被改过
    就不写,回 409 `stale`。"""
    instance = my_instance(db, instance_id, user)
    try:
        return workflow_library.annotate(
            db, instance, body.path, modified=body.modified,
            app=body.app.model_dump() if body.app is not None else None, results=body.results,
        )
    except _WORKFLOW_LIBRARY_ERRORS as exc:
        raise _workflow_library_failed(exc) from exc


@router.post("/plugins/instances/{instance_id}/workflow-library/app/live", response_model=WorkflowAppOut)
def get_canvas_app(instance_id: str, body: WorkflowCanvasRequest, db: DbSession, user: CurrentUser) -> dict:
    """工作台的「应用」面板(ADR 0038 §3):画布上现在这张(含没存的改动)的应用表单。不读、不写那台机器上的文件。"""
    instance = my_instance(db, instance_id, user)
    try:
        return workflow_library.app_live(db, instance, body.content)
    except _WORKFLOW_LIBRARY_ERRORS as exc:
        raise _workflow_library_failed(exc) from exc


@router.post("/plugins/instances/{instance_id}/workflow-library/app/marks", response_model=WorkflowCanvasMarksOut)
def get_canvas_marks(instance_id: str, body: WorkflowCanvasMarksRequest, db: DbSession, user: CurrentUser) -> dict:
    """应用表单和结果标记写进画布要改成的样子(界面经桥改画布,存盘是 ComfyUI 自己的保存)。不写那台机器上的文件。"""
    instance = my_instance(db, instance_id, user)
    try:
        return workflow_library.app_marks(
            db, instance, body.content, app=body.app.model_dump() if body.app is not None else None, results=body.results,
        )
    except _WORKFLOW_LIBRARY_ERRORS as exc:
        raise _workflow_library_failed(exc) from exc


@router.post("/plugins/instances/{instance_id}/workflow-library/run", response_model=GenerationCreateResponse)
def run_canvas(instance_id: str, body: WorkflowCanvasRunRequest, db: Tx, user: CurrentUser) -> GenerationCreateResponse:
    """工作台的「运行」(ADR 0038 §6):跑画布上现在这张,建一个普通的生成任务(模型是 `path` 那张工作流)。"""
    instance = my_instance(db, instance_id, user)
    try:
        created, job = workflow_library.run_canvas(
            db, user, instance, workspace_id=body.workspace_id, project_id=body.project_id, path=body.path,
            prompt=body.prompt, workflow=body.workflow, client_id=body.client_id,
        )
    except GenerationDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except _WORKFLOW_LIBRARY_ERRORS as exc:
        raise _workflow_library_failed(exc) from exc
    return GenerationCreateResponse(generation=GenerationJobOut.model_validate(created), job=job)


@router.post("/plugins/instances/{instance_id}/workflow-library/inspect", response_model=WorkflowLibraryImportOut)
def inspect_workflow_import(instance_id: str, body: WorkflowLibraryImportRequest, db: DbSession, user: CurrentUser) -> dict:
    """导入前先认一遍(不改那台机器):换成界面格式的那张图和它的预览。"""
    instance = my_instance(db, instance_id, user)
    try:
        return workflow_library.inspect_import(db, instance, text=body.text, data=body.data, filename=body.filename,
                                               url=body.url)
    except _WORKFLOW_LIBRARY_ERRORS as exc:
        raise _workflow_library_failed(exc) from exc


@router.post("/plugins/instances/{instance_id}/workflow-library/save", response_model=WorkflowPathOut)
def save_workflow(instance_id: str, body: WorkflowLibrarySaveRequest, db: Tx, user: CurrentUser) -> dict:
    """把导入的那张存进那台服务器的 workflows/(不覆盖)。"""
    instance = my_instance(db, instance_id, user)
    try:
        return workflow_library.save(db, instance, body.path, body.content)
    except _WORKFLOW_LIBRARY_ERRORS as exc:
        raise _workflow_library_failed(exc) from exc


@router.post("/plugins/instances/{instance_id}/workflow-library/install-nodes", response_model=JobOut)
def install_workflow_nodes(instance_id: str, body: WorkflowInstallNodesRequest, db: Tx, user: CurrentUser) -> Job:
    """经这个连接(ComfyUI-Manager)装缺的节点包:一个后台任务,装完要重启 ComfyUI 才加载。"""
    instance = my_instance(db, instance_id, user)
    try:
        return workflow_library.start_node_install(db, user, instance, workspace_id=body.workspace_id, packs=body.packs)
    except _WORKFLOW_LIBRARY_ERRORS as exc:
        raise _workflow_library_failed(exc) from exc


@router.post("/plugins/instances/{instance_id}/workflow-library/reboot", response_model=WorkflowRebootOut)
def reboot_workflow_server(instance_id: str, db: DbSession, user: CurrentUser) -> dict:
    """经这个连接(ComfyUI-Manager)重启那台 ComfyUI,等它回来(正在跑的任务会中断 —— 界面上确认过)。"""
    instance = my_instance(db, instance_id, user)
    try:
        return workflow_library.reboot(db, instance)
    except _WORKFLOW_LIBRARY_ERRORS as exc:
        raise _workflow_library_failed(exc) from exc


@router.post("/plugins/instances/{instance_id}/workflow-library/copy", response_model=WorkflowPathOut)
def copy_workflow(instance_id: str, body: WorkflowCopyRequest, db: Tx, user: CurrentUser) -> dict:
    """在那台服务器上复制一张(不覆盖)。"""
    instance = my_instance(db, instance_id, user)
    try:
        return workflow_library.copy(db, instance, body.path, body.new_path)
    except _WORKFLOW_LIBRARY_ERRORS as exc:
        raise _workflow_library_failed(exc) from exc


@router.post("/plugins/instances/{instance_id}/workflow-library/rename", response_model=WorkflowPathOut)
def rename_workflow(instance_id: str, body: WorkflowRenameRequest, db: Tx, user: CurrentUser) -> dict:
    """在那台服务器上改名 / 挪目录(不覆盖)。"""
    instance = my_instance(db, instance_id, user)
    try:
        return workflow_library.rename(db, instance, body.path, body.new_path)
    except _WORKFLOW_LIBRARY_ERRORS as exc:
        raise _workflow_library_failed(exc) from exc


@router.post("/plugins/instances/{instance_id}/workflow-library/trash", response_model=WorkflowPathOut)
def trash_workflow(instance_id: str, body: WorkflowTrashRequest, db: Tx, user: CurrentUser) -> dict:
    """「删除」:挪进那台服务器上的回收目录,能恢复。"""
    instance = my_instance(db, instance_id, user)
    try:
        return workflow_library.trash(db, instance, body.path)
    except _WORKFLOW_LIBRARY_ERRORS as exc:
        raise _workflow_library_failed(exc) from exc


@router.post("/plugins/instances/{instance_id}/workflow-library/restore", response_model=WorkflowPathOut)
def restore_workflow(instance_id: str, body: WorkflowRestoreRequest, db: Tx, user: CurrentUser) -> dict:
    """从回收目录挪回去(原处被占了就撞名,带着新名字再来)。"""
    instance = my_instance(db, instance_id, user)
    try:
        return workflow_library.restore(db, instance, body.path, body.new_path)
    except _WORKFLOW_LIBRARY_ERRORS as exc:
        raise _workflow_library_failed(exc) from exc


@router.post("/plugins/instances/{instance_id}/workflow-library/folders", response_model=WorkflowPathOut)
def create_workflow_folder(instance_id: str, body: WorkflowFolderRequest, db: Tx, user: CurrentUser) -> dict:
    """在那台服务器的 workflows/ 里新建一个文件夹。已经有了回 409(带建议名)。"""
    instance = my_instance(db, instance_id, user)
    try:
        return workflow_library.make_folder(db, instance, body.path)
    except _WORKFLOW_LIBRARY_ERRORS as exc:
        raise _workflow_library_failed(exc) from exc


@router.post("/plugins/instances/{instance_id}/workflow-library/folders/rename", response_model=WorkflowPathOut)
def rename_workflow_folder(instance_id: str, body: WorkflowFolderRenameRequest, db: Tx, user: CurrentUser) -> dict:
    """文件夹改名 / 挪到别的文件夹里:里面的工作流跟着换路径。目标已经有了回 409(带建议名),不合并进去。"""
    instance = my_instance(db, instance_id, user)
    try:
        return workflow_library.rename_folder(db, instance, body.path, body.new_path)
    except _WORKFLOW_LIBRARY_ERRORS as exc:
        raise _workflow_library_failed(exc) from exc


@router.post("/plugins/instances/{instance_id}/workflow-library/folders/trash", response_model=WorkflowPathOut)
def trash_workflow_folder(instance_id: str, body: WorkflowFolderRequest, db: Tx, user: CurrentUser) -> dict:
    """删除一个文件夹:只删空的,挪进回收目录。里面还有文件回 409(`not_empty`,带着几个)。"""
    instance = my_instance(db, instance_id, user)
    try:
        return workflow_library.trash_folder(db, instance, body.path)
    except _WORKFLOW_LIBRARY_ERRORS as exc:
        raise _workflow_library_failed(exc) from exc


@router.patch("/plugins/instances/{instance_id}/capabilities", response_model=PluginInstanceOut)
def update_capabilities(
    instance_id: str, body: PluginCapabilityUpdate, db: Tx, user: CurrentUser
) -> dict:
    try:
        instance = my_instance(db, instance_id, user)
        inst.set_exposed(db, instance, body.tools)
    except PluginDomainError as exc:
        raise _fail(exc) from exc
    return _instance(db, instance)


@router.get("/plugins/instances/{instance_id}/permissions", response_model=list[PluginPermissionGrantOut])
def list_instance_permissions(instance_id: str, db: DbSession, user: CurrentUser) -> list:
    try:
        return inst.list_permissions(db, my_instance(db, instance_id, user))
    except PluginDomainError as exc:
        raise _fail(exc, 404) from exc


@router.patch("/plugins/instances/{instance_id}/permissions", response_model=list[PluginPermissionGrantOut])
def update_instance_permissions(
    instance_id: str, body: PluginPermissionGrantUpdate, db: DbSession, user: CurrentUser
) -> list:
    # 授权是提权路径:未门禁的调用方可以先授权再调用,两个请求就绕过了确认。
    try:
        return inst.set_permissions(db, my_instance(db, instance_id, user), body.grants)
    except PluginDomainError as exc:
        raise _fail(exc) from exc


@router.get("/plugins/instances/{instance_id}/credentials", response_model=list[PluginCredentialOut])
def list_instance_credentials(instance_id: str, db: DbSession, user: CurrentUser) -> list[dict]:
    try:
        return inst.describe_credentials(db, my_instance(db, instance_id, user))
    except PluginDomainError as exc:
        raise _fail(exc, 404) from exc


@router.patch("/plugins/instances/{instance_id}/credentials", response_model=list[PluginCredentialOut])
def update_instance_credentials(
    instance_id: str, body: PluginCredentialUpdate, db: DbSession, user: CurrentUser
) -> list[dict]:
    try:
        instance = my_instance(db, instance_id, user)
        inst.set_credentials(db, instance, body.values)
        # 凭据是连上服务的前提,填完顺手重拉一次清单 —— 否则用户填完 key 还要再找一个
        # 「刷新」按钮点一下,而中间那段时间插件看起来像是坏的。宿主侧已经在 set_credentials 里通知过了。
        try:
            tools_domain.refresh_tools(db, instance, notify=False)
        except PluginDomainError:
            pass
        return inst.describe_credentials(db, instance)
    except PluginDomainError as exc:
        raise _fail(exc) from exc


# --- 能力 ---------------------------------------------------------------

@router.get("/plugins/tools", response_model=list[PluginToolOut])
def list_exposed_tools(db: DbSession, user: CurrentUser) -> list[dict]:
    """所有可用实例**暴露**的工具。智能体工具表与工作流节点面板读的就是这一份。"""
    return tools_domain.exposed(db, user.id)


@router.post("/plugins/instances/{instance_id}/tools/{tool_name}/invoke", response_model=PluginInvocationOut)
def invoke_tool(
    instance_id: str, tool_name: str, body: PluginInvokeRequest, db: Tx, user: CurrentUser
) -> PluginInvocation:
    # 归属判定与 my_instance 同一个回答;工作区由调用界面指定,入库前先过写权限(见 domain/plugins/use_cases)。
    try:
        return plugin_use_cases.invoke_tool(
            db, user, instance_id, tool_name, body.input, workspace_id=body.workspace_id
        )
    except PluginDomainError as exc:
        raise _fail(exc) from exc


# --- 调用记录 -----------------------------------------------------------

@router.get("/plugins/invocations", response_model=list[PluginInvocationOut])
def list_invocations(db: DbSession, user: CurrentUser, instance_id: str | None = None) -> list[PluginInvocation]:
    """**我自己接的那些**的调用记录。

    记录里带着每次调用的 input/output —— 别人的请求参数和返回内容,没有任何理由出现在我这儿。
    此前这里不做过滤,因为那时接入本来就是所有人共用的一份。
    """
    stmt = select(PluginInvocation).where(PluginInvocation.instance_id.in_(_my_instance_ids(db, user)))
    if instance_id:
        stmt = stmt.where(PluginInvocation.instance_id == instance_id)
    return list(db.scalars(stmt.order_by(PluginInvocation.created_at.desc())))


@router.delete("/plugins/invocations/{invocation_id}", status_code=204)
def delete_invocation(invocation_id: str, db: DbSession, user: CurrentUser) -> None:
    obj = db.get(PluginInvocation, invocation_id)
    if obj is not None:
        my_instance(db, obj.instance_id, user)  # 别人的记录删不得,也不该知道它存在
        db.delete(obj)
        db.commit()


@router.delete("/plugins/invocations", status_code=204)
def clear_invocations(db: DbSession, user: CurrentUser, instance_id: str | None = None) -> None:
    """清空**我自己**的调用记录;带 instance_id 只清该接入的。"""
    if instance_id:
        my_instance(db, instance_id, user)
    stmt = select(PluginInvocation).where(PluginInvocation.instance_id.in_(_my_instance_ids(db, user)))
    if instance_id:
        stmt = stmt.where(PluginInvocation.instance_id == instance_id)
    for obj in db.scalars(stmt):
        db.delete(obj)
    db.commit()


# --- 卸载 ---------------------------------------------------------------
#
# **必须声明在最后。** `/plugins/{package_id}` 是个吃通配的路径,而 FastAPI 按声明顺序匹配 ——
# 它在上面时会把 `DELETE /plugins/invocations` 一并吃掉,当成"卸载一个叫 invocations 的包",
# 于是清空调用记录这件事从来就没成功过(管理员来也是一句 "Plugin not found")。
# 两条路由都要求部署管理员的年代看不出来:两边都 403/404,像是权限不够。

@router.delete("/plugins/{package_id}", status_code=204)
def uninstall_package(package_id: str, db: Tx, user: CurrentUser) -> None:
    """卸载:删掉插件目录,连同它的实例、凭据、授权、调用记录。

    **连目录一起删**,否则下一次扫描又把它装回来 —— 用户看到的是"我删了它怎么又回来了"。
    """
    ensure_deployment_admin(db, user)
    try:
        pkg.uninstall(db, package_id, settings.plugins_dir)
    except PluginDomainError as exc:
        raise _fail(exc, 404) from exc


@router.get("/plugins/instances/{instance_id}/oauth")
def plugin_oauth_start(instance_id: str, db: DbSession, user: CurrentUser) -> dict[str, str]:
    """拿授权链接。**只是拼一个 URL**,这一步不碰网络也不写任何东西。

    用户点开它、在对方站点上登录并同意,然后把授权码贴回来(见下面的 complete)。
    多这一次粘贴,换来的是这条通路上没有任何可伪造的输入 —— 详见 domain/plugins/oauth
    里那段"为什么不用 mosael:// 接回调"。
    """
    instance = my_instance(db, instance_id, user)
    manifest = inst.manifest_for(db, instance)
    try:
        spec = plugin_oauth.spec_of(manifest)
        url = plugin_oauth.authorize_url(spec, inst.credential_values(db, instance.id))
    except plugin_oauth.PluginOAuthError as exc:
        # 422:是"还差点什么"(没声明 oauth、没填 AppKey),不是服务端故障。
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"authorize_url": url, "redirect_uri": spec.redirect_uri}


@router.post("/plugins/instances/{instance_id}/oauth", response_model=list[PluginCredentialOut])
def plugin_oauth_complete(
    instance_id: str, body: PluginOAuthCode, db: DbSession, user: CurrentUser
) -> list[dict]:
    """拿授权码换令牌,写回插件声明的那几个凭据键。

    **只写对方真的回了的字段**(见 credentials_from_token):刷新时常常只回 access_token,
    把缺失当空串写回去会抹掉已有的 refresh_token —— 而那一份丢了要重新走一遍授权。
    """
    instance = my_instance(db, instance_id, user)
    manifest = inst.manifest_for(db, instance)
    try:
        spec = plugin_oauth.spec_of(manifest)
        values = plugin_oauth.exchange_code(spec, inst.credential_values(db, instance.id), body.code)
    except plugin_oauth.PluginOAuthError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    inst.set_credentials(db, instance, values)
    try:
        tools_domain.refresh_tools(db, instance, notify=False)
    except PluginDomainError:
        pass
    return inst.describe_credentials(db, instance)
