"""本机服务的接口(ADR 0041):一个连接背后由宿主起停的那个进程。

**建、改、起、停、认目录、补装、看安装计划、装、取消安装都要部署管理员** —— 起一个目录里的代码就是在这台机器上运行它
(多人部署时进程跑在服务器上)。看状态、看日志、`ensure`(工作台打开前请宿主先起好)只要是这个连接的主人:那是用它,不是管它。连接归人(见
`plugins.my_instance`),别人的连接一律 404。
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Response

from app.api.deps import CurrentUser, DbSession, Tx
from app.api.routes.plugins import my_instance
from app.api.schemas import (
    LocalServiceAddNodesOut,
    LocalServiceAddNodesRequest,
    LocalServiceDetectOut,
    LocalServiceDetectRequest,
    LocalServiceDiscoveryOut,
    LocalServiceInstallRequest,
    LocalServiceLogsOut,
    LocalServiceOut,
    LocalServicePlanOut,
    LocalServiceUpdate,
)
from app.core.i18n import tr
from app.db.models import PluginInstance, User
from app.domain import local_services
from app.domain.local_services import LocalServiceError
from app.domain.permissions import ensure_deployment_admin
from app.domain.plugins import PluginDomainError
from app.domain.plugins.runtime import PluginRuntimeError

router = APIRouter(tags=["local-services"])


def _failed(exc: Exception) -> HTTPException:
    """本机服务自己说的按它的状态码;插件那一头说的(认不出目录、下载失败)原话交回,422。"""
    status = exc.status if isinstance(exc, LocalServiceError) else 422
    return HTTPException(status_code=status, detail=str(exc))


_ERRORS = (LocalServiceError, PluginDomainError, PluginRuntimeError)


def _out(db: DbSession, instance: PluginInstance, user: User) -> dict | None:
    found = local_services.status(db, instance)
    return {**found, "can_manage": bool(user.is_deployment_admin)} if found is not None else None


def _required(db: DbSession, instance: PluginInstance, user: User) -> dict:
    found = _out(db, instance, user)
    if found is None:
        raise HTTPException(status_code=404, detail=tr("localServiceErr_notConfigured"))
    return found


@router.get("/plugins/instances/{instance_id}/local-service", response_model=LocalServiceOut | None)
def get_local_service(instance_id: str, db: DbSession, user: CurrentUser) -> dict | None:
    """这个连接的本机服务:配置和此刻的状态。没用本机服务(连一台服务器)是 null。"""
    return _out(db, my_instance(db, instance_id, user), user)


@router.put("/plugins/instances/{instance_id}/local-service", response_model=LocalServiceOut)
def put_local_service(instance_id: str, body: LocalServiceUpdate, db: Tx, user: CurrentUser) -> dict:
    """建或改。第一次建时选定端口、写进连接的服务器地址。换目录、换解释器要带 `confirm_run_code`。"""
    ensure_deployment_admin(db, user)
    instance = my_instance(db, instance_id, user)
    try:
        local_services.configure(
            db, instance, mode=body.mode, directory=body.directory, python=body.python, listen_lan=body.listen_lan,
            keep_running=body.keep_running, extra_args=body.extra_args, port=body.port,
            confirm_run_code=body.confirm_run_code,
        )
    except _ERRORS as exc:
        raise _failed(exc) from exc
    return _required(db, instance, user)


@router.delete("/plugins/instances/{instance_id}/local-service", status_code=204)
def delete_local_service(instance_id: str, db: Tx, user: CurrentUser) -> Response:
    """不用本机服务了(回到「连一台服务器」):停掉它,删掉这份配置。"""
    ensure_deployment_admin(db, user)
    try:
        local_services.remove(db, my_instance(db, instance_id, user))
    except _ERRORS as exc:
        raise _failed(exc) from exc
    return Response(status_code=204)


@router.post("/plugins/instances/{instance_id}/local-service/detect", response_model=LocalServiceDetectOut)
def detect_local_service(instance_id: str, body: LocalServiceDetectRequest, db: DbSession, user: CurrentUser) -> dict:
    """认一个目录:认没认出来、用哪个解释器、显卡、缺什么。会试跑一次插件说的那几行,所以要先确认过。不存任何东西。"""
    ensure_deployment_admin(db, user)
    instance = my_instance(db, instance_id, user)
    if not body.confirm_run_code:
        raise HTTPException(status_code=422, detail=tr("localServiceErr_confirmRequired"))
    try:
        return local_services.detect(db, instance, body.directory, body.python)
    except _ERRORS as exc:
        raise _failed(exc) from exc


@router.post("/plugins/instances/{instance_id}/local-service/start", response_model=LocalServiceOut)
def start_local_service(instance_id: str, db: DbSession, user: CurrentUser) -> dict:
    """起。马上回来(状态是「启动中」),界面接着轮询。"""
    ensure_deployment_admin(db, user)
    instance = my_instance(db, instance_id, user)
    try:
        local_services.start(db, instance)
    except _ERRORS as exc:
        raise _failed(exc) from exc
    return _required(db, instance, user)


@router.post("/plugins/instances/{instance_id}/local-service/stop", response_model=LocalServiceOut)
def stop_local_service(instance_id: str, db: DbSession, user: CurrentUser) -> dict:
    """停:先请它自己退,10 秒后强杀整组。"""
    ensure_deployment_admin(db, user)
    instance = my_instance(db, instance_id, user)
    local_services.stop(instance.id)
    return _required(db, instance, user)


@router.post("/plugins/instances/{instance_id}/local-service/restart", response_model=LocalServiceOut)
def restart_local_service(instance_id: str, db: DbSession, user: CurrentUser) -> dict:
    """重启:停了再起。马上回来,界面接着轮询。"""
    ensure_deployment_admin(db, user)
    instance = my_instance(db, instance_id, user)
    try:
        local_services.restart(db, instance)
    except _ERRORS as exc:
        raise _failed(exc) from exc
    return _required(db, instance, user)


@router.post("/plugins/instances/{instance_id}/local-service/ensure", response_model=LocalServiceOut | None)
def ensure_local_service(instance_id: str, db: DbSession, user: CurrentUser) -> dict | None:
    """要用它了(工作台打开之前):停着就起,**等它就绪再回来**。没用本机服务的连接回 null,什么都不做。"""
    instance = my_instance(db, instance_id, user)
    if local_services.status(db, instance) is None:
        return None
    try:
        local_services.ensure_running(db, instance)
    except _ERRORS as exc:
        raise _failed(exc) from exc
    return _required(db, instance, user)


@router.get("/plugins/instances/{instance_id}/local-service/logs", response_model=LocalServiceLogsOut)
def get_local_service_logs(
    instance_id: str, db: DbSession, user: CurrentUser, limit: int = 400,
    source: Literal["service", "install"] = "service",
) -> dict:
    """最近的日志(它自己说的话,原样),和完整日志在哪个文件。`source=install`:让 Mosael 装的那几步的输出。"""
    instance = my_instance(db, instance_id, user)
    _required(db, instance, user)
    if source == "install":
        return {"lines": local_services.recent_install_logs(instance.id, limit),
                "path": str(local_services.install_log_path(instance.id))}
    return {"lines": local_services.recent_logs(instance.id, limit), "path": str(local_services.log_path(instance.id))}


@router.get("/plugins/instances/{instance_id}/local-service/plan", response_model=LocalServicePlanOut)
def plan_local_service(instance_id: str, db: DbSession, user: CurrentUser) -> dict:
    """让 Mosael 装之前的安装计划:这台机器能不能装、装哪种 PyTorch、要多少空间、分几步(接着装时哪几步已经做完)、从哪儿下。
    只看、不写;部署管理员(那是这台机器上的事)。"""
    ensure_deployment_admin(db, user)
    instance = my_instance(db, instance_id, user)
    try:
        return local_services.plan(db, instance)
    except _ERRORS as exc:
        raise _failed(exc) from exc


@router.post("/plugins/instances/{instance_id}/local-service/install", response_model=LocalServiceOut)
def install_local_service(instance_id: str, body: LocalServiceInstallRequest, db: DbSession, user: CurrentUser) -> dict:
    """让 Mosael 装(或接着装、重建运行环境):这个连接改成「让 Mosael 装」、选好端口,后台开始装,马上回来,界面接着轮询。
    要确认过(会在这台机器上下载、运行代码)。

    **先提交、再开始装**:安装线程自己开会话读这一行 —— 没提交它就看不见(所以这里不用 `Tx`,提交写在中间)。"""
    ensure_deployment_admin(db, user)
    instance = my_instance(db, instance_id, user)
    if not body.confirm_run_code:
        raise HTTPException(status_code=422, detail=tr("localServiceErr_confirmRequired"))
    try:
        local_services.prepare_install(db, instance)
        db.commit()
        local_services.begin_install(db, instance, flavour=body.flavour)
    except _ERRORS as exc:
        db.rollback()
        raise _failed(exc) from exc
    return _required(db, instance, user)


@router.post("/plugins/instances/{instance_id}/local-service/install/cancel", response_model=LocalServiceOut)
def cancel_local_service_install(instance_id: str, db: DbSession, user: CurrentUser) -> dict:
    """取消正在装的:插件停在手上那一步,下次「接着装」从它开始。"""
    ensure_deployment_admin(db, user)
    instance = my_instance(db, instance_id, user)
    local_services.cancel_install(instance.id)
    return _required(db, instance, user)


@router.post("/plugins/instances/{instance_id}/local-service/add-nodes", response_model=LocalServiceAddNodesOut)
def add_local_service_nodes(
    instance_id: str, body: LocalServiceAddNodesRequest, db: DbSession, user: CurrentUser,
) -> dict:
    """补装插件说缺的节点(界面问过人:会往那个目录里写、要下载)。装进去下次起才加载。"""
    ensure_deployment_admin(db, user)
    instance = my_instance(db, instance_id, user)
    if not body.confirm:
        raise HTTPException(status_code=422, detail=tr("localServiceErr_confirmRequired"))
    try:
        return local_services.add_nodes(db, instance)
    except _ERRORS as exc:
        raise _failed(exc) from exc


@router.get("/plugins/{package_id}/local-services/discover", response_model=LocalServiceDiscoveryOut)
def discover_local_services(package_id: str, db: DbSession, user: CurrentUser) -> dict:
    """本机有没有已经在跑的这种服务(插件页上「本机发现一个,要连上吗」)。只给部署管理员:那是这台机器上的事。"""
    ensure_deployment_admin(db, user)
    try:
        return {"servers": local_services.discover(db, package_id)}
    except _ERRORS as exc:
        raise _failed(exc) from exc
