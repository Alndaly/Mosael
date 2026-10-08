from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, DbSession, Tx
from app.api.schemas import (
    AiRuntimeConfigOut,
    AiRuntimeConfigUpdate,
    InstallSourceOut,
    InstallSourceUpdate,
    NetworkConfigOut,
    NetworkConfigUpdate,
)
from app.db.models import NetworkConfig
from app.domain import ai_runtime
from app.domain.network import apply_to_process, get_config as get_network
from app.domain.voices import tts_settings
from app.domain.permissions import ensure_deployment_admin

router = APIRouter(tags=["settings"])
logger = logging.getLogger(__name__)

def _network_out(row: NetworkConfig) -> NetworkConfigOut:
    return NetworkConfigOut(
        proxy_url=row.proxy_url,
        no_proxy=row.no_proxy,
    )


@router.get("/settings/network", response_model=NetworkConfigOut)
def get_network_config(db: DbSession, user: CurrentUser) -> NetworkConfigOut:
    ensure_deployment_admin(db, user)
    return _network_out(get_network(db))


@router.put("/settings/network", response_model=NetworkConfigOut)
def update_network_config(body: NetworkConfigUpdate, db: DbSession, user: CurrentUser) -> NetworkConfigOut:
    """改出站代理。立刻对本进程生效;sidecar 是每次新起的进程,下一次调用就带上新设置。

    内嵌浏览器由 Electron 侧自己拉取(桌面端启动时和改动后各取一次)——主进程与后端是两个
    进程,共享不了环境变量,只能各自读同一份配置。
    """
    ensure_deployment_admin(db, user)
    row = get_network(db)
    patch = body.model_dump(exclude_unset=True)
    if "proxy_url" in patch and body.proxy_url is not None:
        row.proxy_url = body.proxy_url.strip()
    if "no_proxy" in patch and body.no_proxy is not None:
        row.no_proxy = body.no_proxy.strip()
    db.commit()
    db.refresh(row)
    apply_to_process(row.proxy_url, row.no_proxy)
    logger.info("outbound proxy %s", row.proxy_url or "(direct)")
    return _network_out(row)


@router.get("/settings/ai-runtime", response_model=AiRuntimeConfigOut)
def get_ai_runtime(db: DbSession, user: CurrentUser) -> AiRuntimeConfigOut:
    return AiRuntimeConfigOut(max_retries=ai_runtime.configured_max_retries(db))


@router.put("/settings/ai-runtime", response_model=AiRuntimeConfigOut)
def set_ai_runtime(body: AiRuntimeConfigUpdate, db: Tx, user: CurrentUser) -> AiRuntimeConfigOut:
    """AI 供应商瞬断/限流时的最大重试次数。**对所有 AI 出站调用生效** ——
    对话、生图、生视频、语音、向量化都走同一个带重试的传输层(core/http_retry)。"""
    ensure_deployment_admin(db, user)
    return AiRuntimeConfigOut(max_retries=ai_runtime.save_max_retries(db, body.max_retries))


@router.get("/settings/install-source", response_model=InstallSourceOut)
def get_install_source(db: DbSession, user: CurrentUser) -> InstallSourceOut:
    """「管理 → 下载源」:本机引擎装依赖用的 pip 索引,和插件装包时跟随的 pip / npm 镜像;「让 Mosael 装」本机服务时
    装 CUDA 版 PyTorch 的源和 GitHub 镜像前缀(ADR 0041 §4)。

    **为什么单独一对接口**:pip 那一行历史上存在 tts_config 里(克隆先有了它),于是它在设置页里
    也只出现在克隆表单中 —— 而转写和人声分离装依赖时读的是同一份。存储位置不动(搬表是另一件事),
    但界面和接口不再挂在克隆名下。
    """
    return _install_source_out()


#: 模型下载源能选哪几个:两种 HuggingFace 端点,加上 ModelScope(只有支持它的克隆引擎会走)。
MODEL_SOURCES = ("hf-mirror", "hf", "modelscope")

def _install_source_out() -> InstallSourceOut:
    from app.ai.runtime import config as runtime_config
    from app.domain.local_services import sources as service_sources
    from app.domain.plugins import package_sources

    current = runtime_config.get()
    return InstallSourceOut(
        pip_index=current.pip_index or "",
        npm_registry=current.npm_registry or "",
        pip_presets=package_sources.presets_out("pypi"),
        npm_presets=package_sources.presets_out("npm"),
        pytorch_index=current.pytorch_index or "",
        pytorch_presets=service_sources.pytorch_presets(),
        github_mirror=current.github_mirror or "",
        model_source=current.source,
        model_sources=list(MODEL_SOURCES),
    )


@router.put("/settings/install-source", response_model=InstallSourceOut)
def set_install_source(body: InstallSourceUpdate, db: DbSession, user: CurrentUser) -> InstallSourceOut:
    # 往这台机器上装东西用哪个源,是部署级的设置 —— 和装引擎本身同一条权限。
    ensure_deployment_admin(db, user)
    from app.ai.runtime import config as runtime_config
    from app.domain.local_services import sources as service_sources
    from app.domain.plugins import package_sources
    from app.domain.plugins.errors import PluginDomainError

    row = tts_settings.saved_row(db)
    try:
        #: 只写给了的那几个字段 —— 克隆那几项(引擎、解释器、下载源、fish 目录)一个都不碰。
        if body.pip_index is not None:
            row.pip_index = package_sources.normalize("pypi", body.pip_index)
        if body.npm_registry is not None:
            row.npm_registry = package_sources.normalize("npm", body.npm_registry)
        # 「让 Mosael 装」的两行(ADR 0041 §4):PyTorch 源、GitHub 镜像前缀
        if body.pytorch_index is not None:
            row.pytorch_index = service_sources.normalize_pytorch_index(body.pytorch_index)
        if body.github_mirror is not None:
            row.github_mirror = service_sources.normalize_github_mirror(body.github_mirror)
        model_source_changed = body.model_source is not None and body.model_source != row.source
        if body.model_source is not None:
            row.source = body.model_source
    except PluginDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    runtime_config.refresh()
    if model_source_changed:
        from app.ai.runtime import tts_daemon, tts_models

        # 和改克隆设置同一套收尾:探测缓存、上次失败的那句话按旧源算的;常驻的合成进程带着旧源的 env。
        tts_models.clear_runtime_probes()
        tts_models.forget_failures()
        tts_daemon.pool().drop_all()
    return _install_source_out()
