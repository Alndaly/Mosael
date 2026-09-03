from __future__ import annotations

import logging

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import AiRuntimeConfigOut, AiRuntimeConfigUpdate, NetworkConfigOut, NetworkConfigUpdate
from app.core.http_retry import set_max_retries
from app.db.models import AiRuntimeConfig, NetworkConfig
from app.domain.network import apply_to_process, effective_no_proxy, get_config as get_network
from app.domain.permissions import ensure_deployment_admin

router = APIRouter(tags=["settings"])
logger = logging.getLogger(__name__)

def _network_out(row: NetworkConfig) -> NetworkConfigOut:
    return NetworkConfigOut(
        proxy_url=row.proxy_url,
        no_proxy=row.no_proxy,
        effective_no_proxy=effective_no_proxy(row.no_proxy),
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
    row = db.get(AiRuntimeConfig, "default")
    return AiRuntimeConfigOut(max_retries=row.max_retries if row is not None else 3)


@router.put("/settings/ai-runtime", response_model=AiRuntimeConfigOut)
def set_ai_runtime(body: AiRuntimeConfigUpdate, db: DbSession, user: CurrentUser) -> AiRuntimeConfigOut:
    """AI 供应商瞬断/限流时的最大重试次数。**对所有 AI 出站调用生效** ——
    对话、生图、生视频、语音、向量化都走同一个带重试的传输层(domain/ai_retry)。"""
    ensure_deployment_admin(db, user)
    row = db.get(AiRuntimeConfig, "default")
    if row is None:
        row = AiRuntimeConfig(id="default")
        db.add(row)
    row.max_retries = body.max_retries
    db.commit()
    # 推进进程内状态:调用点散在十几个适配器里,其中不少拿不到 db 会话。
    # 与出站代理(domain/network.apply_to_process)同一套做法,改完即时生效、不必重启。
    set_max_retries(row.max_retries)
    return AiRuntimeConfigOut(max_retries=row.max_retries)
