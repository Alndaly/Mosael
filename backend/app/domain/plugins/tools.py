"""实例的**能力**:有哪些工具、哪些对外暴露、怎么调一次。

这是插件唯一的执行路径。智能体、工作流、插件页手动试跑三条入口都走 `invoke` ——
权限校验、凭据注入、调用留痕都在这里,没有谁能绕过它。
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError, tr
from app.db.models import PluginInstance, PluginInvocation, PluginPackage
from app.domain.effects import plugin_tool_effects
from app.domain.jobs import PLUGIN_SLOTS, report_progress
from app.domain.plugins import artifacts, egress as plugin_egress, inputs as plugin_inputs, instances as inst, state as plugin_state
from app.domain.plugins import service_gate
from app.domain.plugins.artifacts import ArtifactError, cleanup_scratch_dir, make_scratch_dir
from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.manifest import (
    CALL_CAPABILITIES,
    CATALOG_CAPABILITIES,
    GENERATION,
    Manifest,
    localized_tool,
    manifest_of,
    text_of,
    tool_label,
)
from app.domain.plugins.mcp_bridge import McpBridgeError, call_tool as mcp_call, discover_tools
from app.domain.plugins.runtime import (
    PluginRuntimeError,
    StreamHooks,
    check_required_input,
    data_dir_for,
    execute_tool,
    stream_tool,
)

logger = logging.getLogger(__name__)


#: 插件自己能声明的最长预算。再长的活该拆步(先准备、再干活),而不是让一次调用挂半小时。
MAX_DECLARED_TIMEOUT_SECONDS = 1800

#: **替宿主做生成**的那个工具能声明的最长预算:6 小时,和远端生成任务的轮询上限是同一个数
#: (contracts.generation.POLL_TIMEOUT_SECONDS)。一段长视频在一块普通显卡上跑一两个小时是常事,
#: 而那 1800 秒的上限是给「一次普通调用」定的。这个上限只防一个永远不回话的对面(ADR 0019),
#: 不是我们等烦了 —— 进度是真的、取消是真的,用户随时能停。
MAX_GENERATION_TIMEOUT_SECONDS = 6 * 3600
#: 生成工具没写预算时的默认值。
DEFAULT_GENERATION_TIMEOUT_SECONDS = 3600


def _declared_timeout(tool: dict[str, Any]) -> float | None:
    """进程插件在 declare 里写的 `timeout_seconds`。没写、写错都当没写(用运行时的默认 60s)。

    **预算该由最知道活有多重的一方给。** 此前只有调用方能给(Blender 互通自己传),插件自己
    说不出「我这一步要三分钟」—— 于是一个渲染视频的工具,不管从哪里调都会在第 60 秒被掐掉。

    认领了生成能力的那个工具按能力给预算(见 MAX_GENERATION_TIMEOUT_SECONDS):不写是 1 小时,
    上限 6 小时。
    """
    generates = GENERATION in _claims(tool)
    raw = tool.get("timeout_seconds")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw <= 0:
        return float(DEFAULT_GENERATION_TIMEOUT_SECONDS) if generates else None
    cap = MAX_GENERATION_TIMEOUT_SECONDS if generates else MAX_DECLARED_TIMEOUT_SECONDS
    return float(min(raw, cap))


def _claims(tool: dict[str, Any]) -> set[str]:
    """这个工具**认领**了哪些宿主能力(工具声明上的 `provides`)。"""
    provides = tool.get("provides")
    return {str(one) for one in provides} if isinstance(provides, list) else set()


def _ensure_data_dir(package_id: str) -> Path:
    path = data_dir_for(package_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def all_tools(db: Session, instance: PluginInstance) -> list[dict[str, Any]]:
    """这个实例**拥有**的工具(不管暴不暴露)。插件页的勾选列表用它。

    进程类插件的清单写在 manifest 里;MCP 实例的清单从服务现拉、缓存在 instance 上 ——
    手抄一份端点清单会随服务升级而烂,而且烂得很安静。
    """
    manifest = inst.manifest_for(db, instance)
    #: 运行时报出的工具(进程插件的 `op: tools`,见 dynamic_tools)—— 只有它们说得出 `mirrors`,形状已在收的时候卡过。
    reported: set[str] = set()
    if manifest.is_mcp:
        raw = list(instance.discovered_tools or [])
    else:
        # 进程插件:清单里声明的,加上它**运行时报出的**(见 dynamic_tools;和 MCP 的清单存在同一格)。
        # 后者的文字原样存着,读的时候按此刻的语言定下来。
        declared = {str(tool.get("name")) for tool in manifest.declared_tools}
        discovered = [tool for tool in (instance.discovered_tools or [])
                      if isinstance(tool, dict) and str(tool.get("name")) not in declared]
        reported = {str(tool.get("name")) for tool in discovered}
        raw = list(manifest.declared_tools) + [localized_tool(tool) for tool in discovered]
    out: list[dict[str, Any]] = []
    for tool in raw:
        if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
            continue
        override = manifest.overrides.get(tool["name"])
        description = (override.description if override and override.description else "") or text_of(
            tool.get("description")
        )
        # 只读默认 False:插件跑的是别人的代码,没有确认门也照样能发请求、写文件,
        # 所以"不确定"落在保守那边 —— 子智能体只拿只读工具。
        #
        # 两个来源:工具自己声明的(进程插件写在 declare 里),和 overrides 里覆盖的
        # (MCP 插件只能这么写 —— 它的清单是从服务拉的)。任一处标了就算。
        read_only = bool((override and override.read_only) or tool.get("read_only"))
        node = (override.node if override else None) or tool.get("node")
        out.append(
            {
                "name": tool["name"],
                "label": tool_label({**tool, "node": node}, override.label if override else ""),
                "description": description,
                "input_schema": tool.get("input_schema") or {"type": "object", "properties": {}},
                "read_only": read_only,
                # 后果(domain/effects):智能体调它之前要不要先问人、按哪一档问。**一处算出来**,
                # 智能体工具表、画板上的能力、插件页的「需确认」徽标读的都是这一个值。
                # 覆盖 > 工具自己声明的 > 包上的 default_effects > external;只读的一律 none。
                "effects": plugin_tool_effects(
                    read_only=read_only,
                    declared=(override.effects if override and override.effects else None) or tool.get("effects"),
                    default=manifest.default_effects or None,
                ),
                "node": node,
                # 只给宿主调的:清单上标了 internal 的,和认领了**目录类**能力(生成、工具清单)的 —— 它们回答「有哪些
                # 模型 / 工具」,本身不是一次能交给人的调用。认领调用类能力(文档解析、降噪……)的是普通工具(ADR 0033)。
                "internal": bool((override and override.internal) or (_claims(tool) & CATALOG_CAPABILITIES)),
                "provides": sorted(_claims(tool)),
                # MCP 的清单是对方服务给的,那里没有这个字段 —— 只认进程插件自己声明的。
                "timeout_seconds": None if manifest.is_mcp else _declared_timeout(tool),
                # 边跑边说进度、取消时先让插件去停远端的活(见 runtime.stream_tool)。只给进程形态:
                # MCP 是别人的协议,我们不往里加字段。
                "stream": (not manifest.is_mcp) and tool.get("stream") is True,
                # 这个工具和一个生成模型是同一件事(运行时报出的工具才说得出,见 dynamic_tools.clean_mirror)——
                # 画板上只留生成那一个入口(boards.transforms 的 mirrored_by_generation)。
                "mirrors": tool.get("mirrors") if tool["name"] in reported else None,
            }
        )
    return out


def refresh_tools(db: Session, instance: PluginInstance, *, notify: bool = True) -> PluginInstance:
    """向 MCP 服务重新要一次工具清单。进程类实例的清单写在 manifest 里,无需刷新。

    插件页的「刷新」也走这里,所以顺带让替宿主做事的那一侧重新问一遍(`notify`,见
    host_capabilities):ComfyUI 里新存了一张工作流,点一下刷新它就该出现在模型选择器里。
    """
    from app.domain.plugins import host_capabilities

    manifest = inst.manifest_for(db, instance)
    if not manifest.is_mcp:
        inst.seed_capabilities(db, instance, manifest, [t["name"] for t in all_tools(db, instance)])
        if notify:
            host_capabilities.notify(db, instance, refresh=True)
        return instance
    for absent in (inst.missing_config(db, instance), inst.missing_credentials(db, instance)):
        if absent:
            raise PluginDomainError("pluginErr_fillFirst", names=tr("punct_listSep").join(absent))
    try:
        discovered = discover_tools(
            _runtime_manifest(manifest), inst.secrets_for(db, instance), plugin_egress.resolve(db, instance, manifest)
        )
    except McpBridgeError as exc:
        # 拉不到的原因记在 `capability_status["tools"]`(和进程插件报工具清单同一格,见 dynamic_tools):
        # 启用、改配置时顺手拉的那一次失败不往外抛,不记下来的话插件页只能说「没有工具」,说不出为什么。
        inst.record_tool_list_failure(db, instance, exc)
        raise PluginDomainError(exc.key, **exc.params) from exc
    instance.discovered_tools = discovered
    db.flush()
    db.refresh(instance)
    # 连同清单一起由 seed_capabilities 提交。
    inst.seed_capabilities(db, instance, manifest, [t["name"] for t in discovered])
    inst.record_tool_list(db, instance, len(discovered))
    return instance


def _runtime_manifest(manifest: Manifest) -> dict[str, Any]:
    """mcp_bridge 收的是一个字典(它比这次重构更早)。在这里做一次转换,而不是把 dataclass
    的形状泄进传输层 —— 那一层只关心怎么连、连哪儿。"""
    runtime = manifest.runtime
    return {
        "_path": manifest.path,
        "kind": "mcp",
        "mcp": {
            "transport": runtime.transport,
            "command": runtime.command,
            "args": runtime.args,
            "url": runtime.url,
            "headers": runtime.headers,
        },
    }


def exposed(db: Session, user_id: str | None) -> list[dict[str, Any]]:
    """**他自己接的**那些可用实例暴露出来的工具。智能体工具表、工作流节点面板、插件页共用这一份。

    可用 = 启用 + 配置齐 + 凭据齐 + 权限已授。不可用的实例整条不出现 —— 让智能体去调一个
    必定 401 的工具,只会烧掉一轮对话来复述一句用户在设置页早就看得到的话。

    `user_id` 是**必填位置参数**(可以显式传 None 表示"不按人过滤",只有后台无人路径这么用):
    接入归人(见 db.models.PluginInstance),漏过滤的地方会让我的智能体拿着**别人的**第三方
    密钥去调 —— 那笔账记在他头上,我这边什么痕迹都没有。给个默认值就等于让漏改的地方静默通过。
    """
    out: list[dict[str, Any]] = []
    stmt = select(PluginInstance).where(PluginInstance.enabled.is_(True))
    if user_id is not None:
        stmt = stmt.where(PluginInstance.owner_user_id == user_id)
    for instance in db.scalars(stmt):
        if inst.blocked_reason(db, instance):
            continue
        package = db.get(PluginPackage, instance.package_id)
        if package is None:
            continue
        chosen = inst.exposed_tools(db, instance.id)
        #: 插件叫什么(按此刻的语言)。节点按包聚合(见 nodes.plugin_node_types),所以节点、画板菜单上
        #: 标「出自哪儿」用的是它,不是连接名 —— 连接名是「阿里云 OSS · 某个桶」这种本机事实。
        package_name = inst.manifest_for(db, instance).name
        for tool in all_tools(db, instance):
            if tool["name"] not in chosen or tool["internal"]:
                continue
            out.append({**tool, "instance_id": instance.id, "instance_name": instance.name,
                        "package_id": package.id, "package_name": package_name})
    return out


def find(db: Session, instance_id: str, tool_name: str) -> dict[str, Any] | None:
    instance = db.get(PluginInstance, instance_id)
    if instance is None:
        return None
    return next((tool for tool in all_tools(db, instance) if tool["name"] == tool_name), None)


def invoke(
    db: Session,
    instance_id: str,
    tool_name: str,
    payload: dict[str, Any],
    *,
    workspace_id: str | None = None,
    project_id: str | None = None,
    timeout: float | None = None,
    host: bool = False,
) -> PluginInvocation:
    """跑一次工具。**插件唯一的执行路径。**

    `host=True` 只给**宿主自己的适配层**(Blender 互通):只有这时,标了 `internal` 的工具(以及认领了
    目录类能力的,见 manifest.CATALOG_CAPABILITIES)才跑得起来。别的入口 —— 智能体、工作流、
    画板、插件页 —— 一律不行,这道门收在这一处:此前是各入口自己挡(工作流执行器判一次、智能体和画板
    靠 `exposed` 过滤),插件页的「试一下」那条路由谁都没挡,一个 POST 就能直接跑 Blender 的原始
    代码执行入口、绕开生成任务直接调生成协议。

    `timeout` 不给就用**工具自己声明的** `timeout_seconds`,再没有就用运行时的默认预算(60s)。
    **借道这条通道的产品功能要自己给** ——
    那 60 秒对标的是「一个插件工具该跑多久」,而 Blender 互通是一条产品功能,只是借道;
    借道不该继承调用者的预算(见 runtime.PLUGIN_TIMEOUT_SECONDS 上那段说明)。

    给了 workspace_id 的话,插件交出的文件产出会在这里收进素材库(见 artifacts):
    输出里的 `artifact` 换成 `asset_id`,调用方拿到的就是一个素材 id,和其它产素材的
    工具一样。没给 workspace_id 就不收 —— 一份素材总得属于某个工作区。

    认领了调用类能力的工具(文档解析、降噪……)产出按那项能力登记的收尾交给调用方(ADR 0033 §3):
    文档解析存成那份文档的一次新解析;没登记收尾的按上面的通用规矩。
    """
    instance = db.get(PluginInstance, instance_id)
    if instance is None:
        raise PluginDomainError("pluginErr_instanceNotFound")
    blocked = inst.blocked_reason(db, instance)
    if blocked:
        raise PluginDomainError("pluginErr_unavailable", name=instance.name, reason=blocked)
    tool = find(db, instance_id, tool_name)
    if tool is None:
        raise PluginDomainError("pluginErr_noSuchTool", name=instance.name, tool=tool_name)
    if tool["internal"] and not host:
        raise PluginDomainError("pluginErr_toolInternal", tool=tool_name)
    if timeout is None:
        timeout = tool.get("timeout_seconds")

    invocation = PluginInvocation(
        instance_id=instance.id, tool_name=tool_name, status="running", input=payload, output={}
    )
    db.add(invocation)
    db.commit()

    manifest = inst.manifest_for(db, instance)
    #: 这个连接往外连走哪条路:子进程的代理变量、后端替它发的请求,都照这一个决定(见 egress)。
    egress = plugin_egress.resolve(db, instance, manifest)
    scratch: Path | None = None
    # 进程隔离:插件崩了、超时了、吐了非 JSON —— 失败的是这次调用记录,不是应用。
    injected = _Injected()
    try:
        payload = plugin_inputs.coerce(tool, payload)
        check_required_input(tool, payload)
        if manifest.is_mcp:
            secrets = inst.secrets_for(db, instance)
            # MCP 那一侧没有 state 槽 —— 它是别人的协议,我们不往里加字段。要记东西的插件
            # 走进程形态(见 domain/plugins/state 的说明)。
            #
            # **取消停不下它。** server 进程是 MCP 客户端库在事件循环里起的,拿不到句柄登记到
            # 任务名下(进程插件能,见 runtime.execute_tool)。任务取消后这次调用照常跑完,
            # 结果被丢掉:工作流在节点边界看到已取消就不再往下走。
            with _plugin_slot(db):
                output = mcp_call(
                    _runtime_manifest(manifest),
                    tool_name,
                    payload,
                    secrets,
                    egress=egress,
                    **({"timeout": timeout} if timeout is not None else {}),
                )
        else:
            scratch = make_scratch_dir()
            # 先落状态再收产出(_run_process 里):刷新出来的令牌得先存住。反过来的话,收产出那一步出任何岔子
            # (下载失败、磁盘满),这次刷新就白做了 —— 而旧令牌已经被百度那边作废了。
            output = _run_process(
                db, instance, manifest, tool, payload, scratch, injected, egress=egress, workspace_id=workspace_id,
                hooks=_tool_hooks() if tool["stream"] else None, timeout=timeout, take_slot=True, notify=True,
            )
        finish = None if manifest.is_mcp else _finisher(tool)
        if finish is not None and scratch is not None:
            # 认领了调用类能力的工具:产出按那项能力收尾(文档解析 → 存成那份文档的解析),谁调都一样(ADR 0033 §3)。
            from app.domain.plugins.host_capabilities import CapabilityCall

            output = finish(db, CapabilityCall(
                instance=instance, tool=tool, payload=payload, output=output, scratch=scratch,
                workspace_id=workspace_id, project_id=project_id,
            ))
        else:
            output = _collect_artifact(
                db, output, scratch, workspace_id=workspace_id, project_id=project_id, fallback_name=tool_name,
                egress=egress, inputs=plugin_inputs.asset_refs(tool, payload),
            )
        invocation.status, invocation.output = "succeeded", output
        inst.note_authorization(db, instance, rejected=False)
    except (PluginRuntimeError, McpBridgeError, ArtifactError, PluginDomainError, LocalizedError) as exc:
        # LocalizedError:能力的收尾说得出的失败(「这不是一份文档」「插件交回的东西不对」);收尾自己的半截东西由它自己收拾。
        invocation.status, invocation.error = "failed", str(exc)
        _persist_failed_state(db, instance, exc, baseline=injected.baseline)
        _note_rejected_authorization(db, instance, exc)
    except Exception as exc:  # noqa: BLE001 — runtime must never bubble
        invocation.status, invocation.error = "failed", tr("pluginErr_runtimeCrashed", detail=str(exc))
    finally:
        cleanup_scratch_dir(scratch)
    db.commit()
    db.refresh(invocation)
    return invocation


#: 流式工具的进度多久往上报一次。插件可能每一步都说一句(采样器 20 步就是 20 行),上报要写库。
_PROGRESS_INTERVAL_SECONDS = 1.0


def _tool_hooks() -> StreamHooks:
    """**普通工具**的流式调用接到哪儿(生成那条由生成执行器自己接,见 generation/plugin_connections)。

    - 进度交给任务总线的上报口(`jobs.report_progress`):在工作流节点里跑时,它成了那个节点的
      `workflow.node.progress` 事件,执行面板上看得到「采样 12/20」;不在任务里(插件页试跑、智能体)就没人听;
    - 回执不记:普通工具的调用不跨重启续等(那是生成任务的事,见 ADR 0020);
    - 取消不靠轮询:在任务里跑时,取消任务会拉下挂在任务名下的开关,先建取消文件让插件去停远端的活。
    """
    last = [0.0]

    def on_progress(fraction: float, message: str) -> None:
        now = time.monotonic()
        if now - last[0] < _PROGRESS_INTERVAL_SECONDS and fraction < 1.0:
            return
        last[0] = now
        report_progress(fraction, message)

    return StreamHooks(on_progress=on_progress, on_task=lambda _task: None, is_cancelled=lambda: False)


def host_tool(db: Session, instance: PluginInstance, capability: str) -> dict[str, Any]:
    """这个实例上**认领** `capability` 的那个工具。没有就说清楚是哪个插件、缺什么。"""
    tool = next((one for one in all_tools(db, instance) if capability in one["provides"]), None)
    if tool is None:
        raise PluginDomainError("pluginErr_capabilityNoTool", name=instance.name, capability=capability)
    return tool


def staged_output(scratch: Path, relative: Any) -> Path | None:
    """插件交回的相对路径 → 暂存目录里那份文件(`collect` 里用)。落在暂存目录外面、或者不存在 → None ——
    不能借它读走别处的文件;调用方用自己领域的错误说「插件交回的东西不对」。"""
    if not relative:
        return None
    target = (scratch / str(relative)).resolve()
    return target if target.is_relative_to(scratch.resolve()) and target.is_file() else None


def staged_artifact(scratch: Path, spec: Any) -> Path | None:
    """一份 `artifact`(`{"path": …}`)→ 暂存目录里那份文件。宿主的入口在暂存目录删之前自己取走(`collect`),
    不进素材库 —— 那是入口自己的落点(降噪完放回视频、配音贴到时间线)。只认交在暂存目录里的:入口要的是
    手上马上有的一份,不替它去下一个地址。"""
    return staged_output(scratch, spec.get("path")) if isinstance(spec, dict) else None


def quiet_hooks() -> StreamHooks:
    """走流式协议(取消文件、进度行)但宿主不看进度的那种调用:降噪、分离、转写这类一段音频进、一段结果出。"""
    return StreamHooks(on_progress=lambda _fraction, _message: None, on_task=lambda _receipt: None,
                       is_cancelled=lambda: False)


@dataclass
class _Injected:
    """这次注入的配置与凭据:写回 state 时按它做比较交换(见 plugins/state.persist),失败时也用它。
    还没走到注入那一步就失败的,它是 None —— 插件根本没跑,没有状态可落。"""

    baseline: dict[str, str] | None = None


def _run_process(
    db: Session,
    instance: PluginInstance,
    manifest: Manifest,
    tool: dict[str, Any],
    payload: dict[str, Any],
    scratch: Path,
    injected: _Injected,
    *,
    egress: plugin_egress.Egress,
    workspace_id: str | None,
    files: dict[str, Path] | None = None,
    hooks: StreamHooks | None,
    timeout: float | None,
    take_slot: bool,
    notify: bool,
) -> dict[str, Any]:
    """进程插件跑一次:素材换成暂存目录里的副本、注入这个连接的配置与凭据、跑子进程(给了 `hooks` 就走流式)、落 state。

    **两条入口共用这一段**(ADR 0033 §3):智能体、工作流、插件页走 `invoke`,宿主自己的入口走 `invoke_host`。
    素材也只有一道暂存(`inputs.materialize`):调用方给的素材 id,和宿主入口手上的文件(`files`)。此前宿主那条
    自己拷文件、自己把路径塞进 payload,插件工具因此分成了两种。
    """
    # 连接背后是宿主起停的本机服务(ADR 0041):停着就先替它起进程(任务里报一句进度),等它就绪在交还连接之后
    # (_plugin_slot)。拿回来的变量告诉插件「这台服务器归宿主管」(装完节点要重启时请宿主重启,不自己去重启它)。
    service = service_gate.prepare(db, instance, progress=hooks.on_progress if hooks is not None else report_progress)
    # 在这里换而不是让插件自己取:它的环境里没有数据库、没有令牌、没有媒体目录,那是隔离边界的一部分。
    resolved = plugin_inputs.materialize(db, tool, payload, scratch, workspace_id=workspace_id, files=files)
    injected.baseline = inst.secrets_for(db, instance)
    env = {**inst.process_env(db, instance), **service.env}
    run_kwargs: dict[str, Any] = {
        "scratch_dir": scratch,
        "data_dir": _ensure_data_dir(manifest.id),
        "egress": egress,
        **({"timeout": timeout} if timeout is not None else {}),
    }
    try:
        with _plugin_slot(db, take=take_slot, wait_ready=service.wait_ready):
            if hooks is not None:
                result = stream_tool(
                    Path(manifest.path), manifest.runtime.entry, tool["name"], resolved, env, hooks=hooks, **run_kwargs,
                )
            else:
                result = execute_tool(Path(manifest.path), manifest.runtime.entry, tool["name"], resolved, env, **run_kwargs)
    except (PluginRuntimeError, PluginDomainError) as exc:
        # 背后是本机服务、而它此刻用不了(停了、在起、起不来、进程在却不应答):原因按它的状态说 —— 插件那句「连不上,
        # 确认它在运行、地址填对」只适合「连一台服务器」。它好好的就照插件说的(工作流本身的错)
        explained = service_gate.explain(db, instance)
        if explained is not None:
            raise explained from exc
        raise
    finally:
        # 用完了:闲置的钟从现在算(本机服务;没有本机服务时什么都不做)
        service.done()
    plugin_state.persist(db, instance, result.state, baseline=injected.baseline, notify=notify)
    return result.output


def _finisher(tool: dict[str, Any]) -> Any:
    """这个工具认领的调用类能力登记的收尾(见 host_capabilities.finisher);没有就是 None,产出按通用规矩收。"""
    from app.domain.plugins import host_capabilities

    for capability in sorted(_claims(tool) & CALL_CAPABILITIES):
        finish = host_capabilities.finisher(capability)
        if finish is not None:
            return finish
    return None


def invoke_host(
    db: Session,
    instance_id: str,
    capability: str,
    payload: dict[str, Any],
    *,
    files: dict[str, Path] | None = None,
    prepare: Callable[[Path], dict[str, Any]] | None = None,
    collect: Callable[[dict[str, Any], Path], dict[str, Any]] | None = None,
    hooks: StreamHooks | None = None,
    timeout: float | None = None,
    record: bool = True,
) -> dict[str, Any]:
    """**宿主自己的入口**调一次认领了 `capability` 的那个工具。和 `invoke` 跑的是同一段(`_run_process`):

    可用性判定(启用 / 配置 / 凭据 / 授权)、只注入这个实例自己的配置与凭据、留一条调用记录、
    状态落库 —— 这些一样不少。不同的只有几处,都是因为调用方是宿主的一个入口:

    - **失败抛异常**,不是回一条失败记录:入口要据此决定下一步(解析任务失败、目录刷新记下原因);
    - `files`:入口手上的文件(转写前抽好的音轨、解析任务里的原件)交给工具的素材入参 —— 和素材 id 同一道暂存;
    - `collect(output, 暂存目录)` 在暂存目录被删**之前**让入口把产出拿走(它有自己的落点:那一行解析、那条字幕轨),
      返回留进调用记录的那一份;不走通用的「文件进素材库」;
    - 给了 `hooks` 就走流式协议(进度、回执、取消,见 runtime.stream_tool);
    - `prepare(暂存目录)` **只给目录类能力**(生成):它的输入是一串带角色的文件,不是工具入参里的素材格子。

    `timeout` 不给就用工具自己声明的预算。

    `record=False` 不留调用记录:宿主**隔一会儿就问一次**的那种(目录指纹,见 generation/plugin_connections)
    不是一次「调用」,每分钟一行会把插件页的调用记录淹掉,真正的调用反而找不到。失败照样抛。

    连接背后是本机服务时,停着就先起、等它就绪(用到时起,ADR 0041);后台刷新目录包在 `service_gate.no_autostart` 里,
    不替它起。
    """
    instance = db.get(PluginInstance, instance_id)
    if instance is None:
        raise PluginDomainError("pluginErr_instanceNotFound")
    blocked = inst.blocked_reason(db, instance)
    if blocked:
        raise PluginDomainError("pluginErr_unavailable", name=instance.name, reason=blocked)
    tool = host_tool(db, instance, capability)
    manifest = inst.manifest_for(db, instance)
    budget = timeout if timeout is not None else tool.get("timeout_seconds")
    invocation = PluginInvocation(
        instance_id=instance.id, tool_name=tool["name"], status="running", input=_recorded(payload), output={}
    )
    if record:
        db.add(invocation)
        db.commit()
    scratch = make_scratch_dir()
    injected = _Injected()
    try:
        sent = prepare(scratch) if prepare is not None else payload
        # 一问一答(问目录)和别的工具调用一样占一个插件名额(jobs.PLUGIN_SLOTS)。流式的那条
        # 不占:它是一次生成 / 一次解析,跑在任务里,受任务派发的上限约束(jobs.MAX_ACTIVE_JOBS)—— 一段跑
        # 一小时的视频占着插件名额,别的插件调用就得陪它等一小时。**两条都先交还连接**(见 _plugin_slot)。
        output = _run_process(
            db, instance, manifest, tool, sent, scratch, injected, egress=plugin_egress.resolve(db, instance, manifest),
            workspace_id=None, files=files, hooks=hooks, timeout=budget, take_slot=hooks is None, notify=False,
        )
        recorded = collect(output, scratch) if collect is not None else output
        invocation.status, invocation.output = "succeeded", recorded
        inst.note_authorization(db, instance, rejected=False)
        # 不留调用记录时也要落这一笔:「需要重新授权」清没清掉,不该取决于这次记不记账。
        db.commit()
        return output
    except Exception as exc:
        invocation.status = "failed"
        invocation.error = str(exc) if isinstance(exc, (PluginRuntimeError, PluginDomainError, ArtifactError)) else tr(
            "pluginErr_runtimeCrashed", detail=str(exc)
        )
        _persist_failed_state(db, instance, exc, baseline=injected.baseline, notify=False)
        _note_rejected_authorization(db, instance, exc)
        db.commit()
        raise
    finally:
        cleanup_scratch_dir(scratch)


#: 问插件一种本机服务的事(`service_*`)缺省等多久。它们只描述、不起进程;最慢的是认目录时试跑一次 `import torch`
#: (插件自己给那一步 30 秒上限),补装节点要下载 —— 那两个由调用方给更长的预算。
SERVICE_OP_TIMEOUT_SECONDS = 30


def invoke_service(
    db: Session,
    package_id: str,
    service_key: str,
    payload: dict[str, Any],
    *,
    instance: PluginInstance | None = None,
    timeout: float = SERVICE_OP_TIMEOUT_SECONDS,
    hooks: StreamHooks | None = None,
) -> dict[str, Any]:
    """宿主问插件**一种本机服务**的事(ADR 0041 的 `service_*` 操作,payload 里的 `op` 说是哪一件):怎么认出一个装好的
    目录、怎么起、补装节点、本机有没有已经在跑的、装一份……交给清单 `services` 里那种服务的 `tool`。

    给了 `hooks` 就走流式协议(`service_install`:一步一行、取消文件停在那一步,见 runtime.stream_tool),而且**不占插件名额**:
    一次安装要十几分钟,别的插件调用不该陪它等(和流式的生成同一个道理)。

    和 `invoke_host` 不同的几处,都因为这是宿主的**管理动作**、不是一次用它干活:

    - 不走「用到时起」那道门 —— 问怎么起的时候它当然还没起;
    - 不留调用记录(插件页的调用记录是给人翻「用它干过什么」的),不落 state;
    - 不看连接停没停用、配没配全:管理员在连接页上给它配本机服务,那时它可能还没启用。只认权限 —— 插件声明的
      权限没授予,它就不该替这个连接做任何事;
    - 没有连接时(插件页上的「本机发现」)什么都不注入:没有配置、没有凭据,也不走代理(问的是本机)。

    失败照抛(`PluginRuntimeError` / `PluginDomainError`)。
    """
    package = db.get(PluginPackage, package_id)
    if package is None:
        raise PluginDomainError("pluginErr_notFound")
    manifest = manifest_of(package)
    service = manifest.service(service_key)
    if service is None:
        raise PluginDomainError("pluginErr_noSuchService", name=manifest.name, service=service_key)
    if instance is not None and inst.pending_permissions(db, instance):
        raise PluginDomainError("pluginErr_unavailable", name=instance.name, reason=inst.blocked_reason(db, instance))
    env = inst.process_env(db, instance) if instance is not None else {}
    egress = plugin_egress.resolve(db, instance, manifest) if instance is not None else plugin_egress.UNDECIDED
    scratch = make_scratch_dir()
    run_kwargs: dict[str, Any] = {"scratch_dir": scratch, "data_dir": _ensure_data_dir(manifest.id), "egress": egress,
                                  "timeout": timeout}
    try:
        with _plugin_slot(db, take=hooks is None):
            if hooks is not None:
                result = stream_tool(Path(manifest.path), manifest.runtime.entry, service.tool, payload, env, hooks=hooks,
                                     **run_kwargs)
            else:
                result = execute_tool(Path(manifest.path), manifest.runtime.entry, service.tool, payload, env, **run_kwargs)
    finally:
        cleanup_scratch_dir(scratch)
    return result.output


def _persist_failed_state(
    db: Session,
    instance: PluginInstance,
    exc: BaseException,
    *,
    baseline: dict[str, str] | None,
    notify: bool = True,
) -> None:
    """插件失败时交回的 `state` 照样落库(见 runtime._final_response)。落不下只记日志 —— 那不该盖掉这次失败本身的原因。

    和成功那条路同一个比较交换(`baseline` 是这次注入的那一份,见 plugins/state.persist):失败的那次
    也可能正和另一次并发刷新令牌。还没走到注入那一步就失败的(`baseline` 为 None),插件根本没跑,没有状态可落。
    """
    state = getattr(exc, "state", None)
    if not isinstance(exc, PluginRuntimeError) or not state or baseline is None:
        return
    try:
        plugin_state.persist(db, instance, state, baseline=baseline, notify=notify)
    except PluginDomainError:
        logger.warning("插件 %s 失败时交回的状态没能记下", instance.id, exc_info=True)


def _note_rejected_authorization(db: Session, instance: PluginInstance, exc: BaseException) -> None:
    """插件说这次失败是因为对方不再接受已存的令牌(`reauthorize: true`,见 runtime._final_response):
    记在连接上,插件页把它标成「需要重新授权」。别的失败不动这个标记 —— 文件不存在不说明令牌好坏。"""
    if isinstance(exc, PluginRuntimeError) and exc.reauthorize:
        inst.note_authorization(db, instance, rejected=True)


#: 调用记录里一个值最多留多长。生成的提示词可能很长,参数表可能很大;记录是给人翻的,不是存档。
_RECORDED_TEXT_LIMIT = 2000


def _recorded(payload: dict[str, Any]) -> dict[str, Any]:
    """留进调用记录的那一份输入:长文本截断(记录不是存档)。"""
    out: dict[str, Any] = {}
    for key, value in payload.items():
        out[key] = value[:_RECORDED_TEXT_LIMIT] if isinstance(value, str) else value
    return out


__all__ = ["COLLECTED_AS", "SERVICE_OP_TIMEOUT_SECONDS", "all_tools", "exposed", "find", "host_tool", "invoke", "invoke_host",
           "invoke_service", "output_port", "quiet_hooks", "refresh_tools", "staged_artifact", "staged_output"]


@contextmanager
def _plugin_slot(
    db: Session, *, take: bool = True, wait_ready: Callable[[], None] | None = None,
) -> Iterator[None]:
    """跑插件进程的那一段:**先交还连接**,等连接背后的本机服务就绪(`wait_ready`,见 service_gate),`take` 时
    再占一个插件名额(jobs.PLUGIN_SLOTS)。

    前面读实例、凭据、素材时会话攥上了一条连接(和一个没结束的读事务),而接下来是等一个子进程 ——
    排队的、跑着的线程都不该一直攥着它(见 jobs 的 RENDER_SLOTS 那段)。流式的生成一跑就是几十分钟到
    几小时:此前那条路不经过这里,每一次插件生成都攥着一条连接和一个读事务直到结束 —— 连接池被几次
    生成占满,SQLite 的 WAL 因为一直有读者而没法回卷。这里提交不会带出半截东西 —— 调用记录在前面
    已经提交过,从那以后到这里只读过实例、凭据和素材。

    等本机服务就绪夹在交还连接和占名额之间:第一次起一台 ComfyUI 可能要一两分钟,这一段既不该攥着连接,也不该
    让别的插件调用陪它等。
    """
    db.commit()
    if wait_ready is not None:
        wait_ready()
    if not take:
        yield
        return
    with PLUGIN_SLOTS:
        yield


#: 一次调用最多交出多少份文件(`artifacts`)。和生成的上限同一个数(见 generation.MAX_OUTPUTS):
#: 再多多半是插件把中间帧也交出来了。
MAX_ARTIFACTS = 64
#: 一份产出上,除了「怎么拿到它」(path / url / headers)之外,插件可以附带的说明(哪个节点、什么类型)。
#: 原样跟着素材 id 回给调用方;只收标量,免得一份产出带着一整棵结构进了对话记录。
_ARTIFACT_TRANSPORT_KEYS = frozenset({"path", "url", "headers"})
#: 一份产出可以说「我是哪个具名输出」(`output`)。键名的样子和工具声明里的输出口一样。
_OUTPUT_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
#: 收产出时**换了名字**的两格(见 _collect_artifact):插件交的 `artifact` 到调用方手里是 `asset_id`,`artifacts`
#: 是 `asset_ids`。工具把这两个名字声明成节点的输出口时,按口取值要到换过的名字上取 —— 此前按同名键取,
#: 那个口永远是空的,下游拿着一个空值往下跑。
COLLECTED_AS = {"artifact": "asset_id", "artifacts": "asset_ids"}


def output_port(output: dict[str, Any], name: str) -> Any:
    """一次调用的返回值里,节点输出口 `name` 的那一格(收产出换过名字的按换过的取)。"""
    if name in output:
        return output[name]
    return output.get(COLLECTED_AS.get(name, name))


def _collect_artifact(
    db: Session,
    output: dict[str, Any],
    scratch: Path | None,
    *,
    workspace_id: str | None,
    project_id: str | None,
    fallback_name: str,
    egress: plugin_egress.Egress,
    inputs: tuple[str, ...] = (),
) -> dict[str, Any]:
    """把输出里的文件产出收进素材库(`inputs` 是这次交给插件的素材,产出记它们为出处):`artifact`(一份)换成 `asset_id`,`artifacts`(一串)换成
    `assets` / `asset_ids`,并在还没有 `asset_id` 时把第一份记成它 —— 下游(工作流里 `{{n1.asset_id}}`)
    不必知道这个工具交的是一份还是几份。

    换掉而不是两个都留:留着的话,下游会拿到一个指向已经删掉的暂存目录的路径 —— 那条路径
    在返回的那一刻就已经失效了(finally 里刚清完),而它看起来完全像个能用的路径。
    """
    single = output.get("artifact")
    many = output.get("artifacts")
    if not isinstance(single, dict) and not isinstance(many, list):
        return output
    specs = [spec for spec in (many if isinstance(many, list) else []) if isinstance(spec, dict)]
    if len(specs) > MAX_ARTIFACTS:
        raise ArtifactError("pluginErr_artifactTooMany", limit=MAX_ARTIFACTS)
    collected = {key: value for key, value in output.items() if key not in ("artifact", "artifacts")}
    if (isinstance(single, dict) or specs) and (workspace_id is None or scratch is None):
        raise ArtifactError("pluginErr_artifactNeedsWorkspace")
    if isinstance(single, dict):
        ref, name = artifacts.register(
            db, single, scratch, workspace_id=workspace_id, project_id=project_id, fallback_name=fallback_name,
            egress=egress, derived_from=inputs,
        )
        collected.update({"asset_id": ref, "asset_name": name})
    if isinstance(many, list):
        assets: list[dict[str, Any]] = []
        for spec in specs:
            ref, name = artifacts.register(
                db, spec, scratch, workspace_id=workspace_id, project_id=project_id, fallback_name=fallback_name,
                egress=egress, derived_from=inputs,
            )
            extras = {
                str(key): value for key, value in spec.items()
                if key not in _ARTIFACT_TRANSPORT_KEYS and key not in ("filename", "output")
                and isinstance(value, (str, int, float, bool))
            }
            assets.append({**extras, "asset_id": ref, "asset_name": name})
            # 具名输出:这一份就是工具声明里的某个输出口(`image_9` —— 那个保存节点的图)。
            # 同名的只认第一份;插件自己在输出里写了同名的一格就不覆盖。
            named = spec.get("output")
            if isinstance(named, str) and _OUTPUT_KEY.match(named) and named not in collected:
                collected[named] = ref
        collected["assets"] = assets
        collected["asset_ids"] = [one["asset_id"] for one in assets]
        if assets and "asset_id" not in collected:
            collected["asset_id"] = assets[0]["asset_id"]
    return collected


def reconcile_orphaned_invocations(db: Session) -> int:
    """重启把跑到一半的插件调用判成失败 —— 它们的子进程 / MCP 连接随旧进程一起没了。

    调用**之前**先落一行 `status="running"`,然后才去跑子进程或 MCP。后端在这中间被杀 ——
    开发态 `--reload` 每改一次文件就是一次 —— 这一行就**永远停在 running**,而插件页的调用
    记录会一直把它列出来,看起来像一次挂住的调用。

    「跨进程执行的东西在重启后要有人收尾」这条规矩在这个仓库里已经建立过四次(jobs、
    agent session、browser、素材),而这是第五处漏掉的。所以它现在登记在
    `domain/restart.py` 的那张表上,由一条棘轮问「你有收尾吗」,不再靠人记得。
    """
    stale = list(db.scalars(select(PluginInvocation).where(PluginInvocation.status == "running")))
    for invocation in stale:
        invocation.status = "failed"
        # 和别的失败原因一样按文案表说(此前这一句是写死的中文,英文界面上照样冒出来)。
        invocation.error = tr("pluginErr_interruptedByRestart")
    if stale:
        db.commit()
    return len(stale)
