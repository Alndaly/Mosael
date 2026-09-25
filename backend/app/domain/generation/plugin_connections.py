"""插件生成供应商在**宿主这一侧**:连接、模型、Adapter(见 docs/adr/0020)。

一个声明了 `provides: ["generation"]` 的插件实例,在生成领域里就是**一条连接**:

- 连接(`ProviderProfile`,`plugin_instance_id` 指回实例,vendor `plugin:<包 id>`)—— 选择器、默认模型、
  生成历史、用量、画板、工作流都指向连接,于是它们一行都不用为插件改;
- 模型行 = 插件目录的缓存(`op: models` 的结果),每行带着插件声明的参数描述符(`declared_capabilities`);
- Adapter(`PluginGenerationAdapter`)在 `ai/providers/registry` 的动态来源里登记,生成执行器照常调它。

插件那一侧的契约(问目录、做一次生成、拷文件进出)在 domain/plugins/generation;这里只负责把它
接到生成领域上。方向是单向的:这里认识插件域,插件域不认识这里(它经 host_capabilities 通知)。
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers import (
    SOURCE_ROLES,
    GenerationAdapter,
    GenerationAdapterContext,
    GenerationAdapterError,
    GenerationProgressCallbacks,
    GenerationRequest,
    GenerationResult,
    metering_from_request,
    register_generation_adapter_source,
    remember_remote_task,
    remote_task_cancelled,
)
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.i18n import LocalizedError, get_current_locale, pick_text
from app.db.models import PluginInstance, ProviderProfile
from app.domain import provider_models
from app.domain.generation.catalog import GENERATION_KINDS
from app.domain.plugins import host_capabilities
from app.domain.plugins import instances as inst
from app.domain.plugins import generation as plugin_generation
from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.manifest import GENERATION
from app.domain.plugins.runtime import PluginCancelled, PluginRuntimeError, StreamHooks

logger = logging.getLogger(__name__)

#: 插件连接的 vendor 前缀。vendor 绑**包**不绑实例:画板、工作流会被导出到别的机器,实例是本机事实
#: —— 和工作流节点类型 `plugin.<包id>.<工具>` 是同一个理由(ADR 0005)。
VENDOR_PREFIX = "plugin:"
#: 宿主接进选择器的生成种类 —— 就是生成目录认的那几种(图像、视频、音频,见 catalog.GENERATION_KINDS),
#: 不在这里另抄一份。


def vendor_for(package_id: str) -> str:
    return f"{VENDOR_PREFIX}{package_id}"


def package_of(vendor: str) -> str:
    """`plugin:<包 id>` → 包 id;不是插件 vendor 回空串。"""
    return vendor[len(VENDOR_PREFIX):] if vendor.startswith(VENDOR_PREFIX) else ""


# ---------------------------------------------------------------------------
# 插件说的模型 → 内核的能力描述符
# ---------------------------------------------------------------------------

#: 没说模式时按种类给最朴素的那一个。
_DEFAULT_MODES = {"image": ["text-to-image"], "video": ["text-to-video"], "audio": ["text-to-audio"]}

#: 宿主**自己有控件**的参数键:它们在插件的 `parameters` 里出现,就翻成描述符里对应的那几格,
#: 由宿主的尺寸下拉、时长选择、种子框来渲染。其余的键进 `parameter_schema`,由通用控件渲染。
_HOST_KEYS = frozenset(
    {
        "seed", "negative_prompt", "size", "resolution", "aspect_ratio", "duration_seconds", "num_images", "generate_audio",
        # 音频(ADR 0022):歌词有宿主的歌词编辑器,纯音乐有宿主的开关 —— 插件叫这两个名字就用宿主的控件。
        "lyrics", "instrumental",
    }
)


def descriptor(model: plugin_generation.PluginModel) -> dict[str, Any]:
    """一个插件模型的能力描述符,和内置目录同形。**不伪造任何值**:插件没给的格子就不出现(ADR 0015)。"""
    caps: dict[str, Any] = {"modes": list(model.modes) or list(_DEFAULT_MODES.get(model.kind, []))}
    keys: list[str] = []
    schema: dict[str, dict[str, Any]] = {}
    for key, spec in model.parameters.items():
        keys.append(key)
        enum = spec.get("enum")
        default = spec.get("default")
        if key == "size":
            if enum:
                caps["sizes"] = [str(one) for one in enum]
            if default not in (None, ""):
                caps["default_size"] = str(default)
        elif key in ("resolution", "aspect_ratio"):
            if enum:
                caps[f"{key}s"] = [str(one) for one in enum]
            if default not in (None, ""):
                caps[f"default_{key}"] = str(default)
        elif key == "duration_seconds":
            if enum:
                caps["duration_seconds"] = [int(one) for one in enum if isinstance(one, (int, float)) and not isinstance(one, bool)]
            else:
                caps["duration_seconds"] = []
                if isinstance(spec.get("minimum"), (int, float)):
                    caps["min_duration_seconds"] = spec["minimum"]
                if isinstance(spec.get("maximum"), (int, float)):
                    caps["max_duration_seconds"] = spec["maximum"]
            if isinstance(default, (int, float)) and not isinstance(default, bool):
                caps["default_duration_seconds"] = default
        elif key == "num_images":
            # 张数的上限:插件在这个参数上说了就用它说的,没说就用「一次最多交回几份」。
            maximum = spec.get("maximum")
            caps["max_num_images"] = int(maximum) if isinstance(maximum, (int, float)) else model.max_outputs
        elif key == "generate_audio":
            caps["supports_generate_audio"] = True
            if isinstance(default, bool):
                caps["default_generate_audio"] = default
        elif key == "instrumental":
            caps.setdefault("boolean_parameters", []).append("instrumental")
            if isinstance(default, bool):
                caps["default_instrumental"] = default
        elif key not in _HOST_KEYS:
            schema[key] = dict(spec)
    limits: dict[str, int] = {}
    required: list[list[str]] = []
    for slot in model.inputs:
        role = slot["role"]
        # 角色只认宿主有的那几种:认不出的角色没有控件、没有校验,挂上去也不知道交给谁。
        if role not in SOURCE_ROLES or role in limits:
            continue
        keys.append(role)
        limits[role] = int(slot["max"])
        if slot.get("required"):
            required.append([role])
    caps["parameter_keys"] = keys
    if schema:
        caps["parameter_schema"] = schema
    if limits:
        caps["source_limits"] = limits
    if required:
        caps["requires_source"] = required
    if model.prompt_dialect:
        caps["prompt_dialect"] = model.prompt_dialect
    return caps


# ---------------------------------------------------------------------------
# 实例 → 连接 + 模型行
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def sync(db: Session, instance: PluginInstance, refresh: bool) -> None:
    """让这个实例的连接和模型行跟上它。`refresh` = 重新问一遍插件有哪些模型。

    连接只在**可用**时启用(启用 + 配置齐 + 凭据齐 + 授权齐):不可用的实例的模型出现在选择器里,
    选了必然失败。没刷新过的也要刷一次 —— 刚接上、还一个模型都没有的连接谈不上「不必刷新」。

    刷新失败不抛:目录保留上一份(ComfyUI 没开不等于它的工作流都没了),失败原因记进
    `capability_status`,插件页看得到。
    """
    manifest = inst.manifest_for(db, instance)
    if GENERATION not in manifest.provides:
        return
    usable = not inst.blocked_reason(db, instance)
    from app.domain.providers import adopt_plugin_connection

    profile = adopt_plugin_connection(
        db,
        plugin_instance_id=instance.id,
        owner_user_id=instance.owner_user_id,
        vendor=vendor_for(manifest.id),
        name=instance.name,
        enabled=usable,
    )
    db.commit()
    previous = dict((instance.capability_status or {}).get(GENERATION) or {})
    if not usable or not (refresh or not previous.get("refreshed_at")):
        return
    try:
        found = plugin_generation.catalog(db, instance)
    except (PluginDomainError, PluginRuntimeError) as exc:
        db.rollback()
        from app.domain.jobs import blame

        inst.set_capability_status(db, instance, GENERATION, {**previous, **blame(exc), "attempted_at": _now()})
        logger.info("插件实例 %s 的生成模型清单没刷出来:%s", instance.id, exc)
        return
    entries = [
        provider_models.DeclaredModel(
            model_id=model.id,
            display_name=model.label,
            capability_ids=[model.kind],
            capabilities={model.kind: descriptor(model)},
        )
        for model in found.models
        if model.kind in GENERATION_KINDS
    ]
    count = provider_models.replace_declared_catalog(db, profile, entries)
    db.commit()
    inst.set_capability_status(
        db,
        instance,
        GENERATION,
        {
            "models": count,
            "refreshed_at": _now(),
            "fingerprint": found.fingerprint,
            "error": "",
            "error_key": "",
            "error_params": {},
        },
    )


def _handler(db: Session, instance: PluginInstance, refresh: bool) -> None:
    sync(db, instance, refresh)


# ---------------------------------------------------------------------------
# 插件页上的「这个实例提供了哪些模型」
# ---------------------------------------------------------------------------


def provided_models(db: Session, instance: PluginInstance) -> list[dict[str, Any]]:
    """这个实例现在提供的模型(模型行上缓存的那一份),给插件页列出来:名字、种类、模式、收什么、几个参数。

    读模型行而不是现问插件:插件页一打开就去拉一遍 ComfyUI 上的每张工作流,和 ADR 0020 拒绝「每次打开
    选择器都现问」是同一个理由。要最新的,点「刷新模型」。
    """
    profile = db.scalar(select(ProviderProfile).where(ProviderProfile.plugin_instance_id == instance.id))
    if profile is None:
        return []
    locale = get_current_locale()
    out: list[dict[str, Any]] = []
    for row in provider_models.list_models(db, profile.id):
        for kind in row.capability_ids or []:
            caps = (row.declared_capabilities or {}).get(kind) or {}
            schema = caps.get("parameter_schema") or {}
            limits = caps.get("source_limits") or {}
            required = {group[0] for group in caps.get("requires_source") or [] if group}
            out.append(
                {
                    "id": row.model_id,
                    "label": row.display_name or row.model_id,
                    "kind": kind,
                    "enabled": row.enabled,
                    "modes": [str(one) for one in caps.get("modes") or []],
                    "inputs": [
                        {"role": role, "max": int(count), "required": role in required}
                        for role, count in limits.items()
                    ],
                    "host_parameters": [
                        key for key in caps.get("parameter_keys") or [] if key in _HOST_KEYS
                    ],
                    "parameters": [
                        {
                            "key": key,
                            "title": pick_text(spec.get("title"), locale) or key,
                            "type": str(spec.get("type") or ""),
                            "advanced": spec.get("x-advanced") is True,
                        }
                        for key, spec in schema.items()
                        if isinstance(spec, dict)
                    ],
                }
            )
    return out


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class PluginGenerationAdapter(GenerationAdapter):
    """一家插件生成供应商在生成执行器眼里的样子。

    - **免钥匙**:凭据在插件实例上,由插件运行时只注入给它自己;
    - **进度与取消**:插件的 `progress` 事件进任务中心,用户取消经取消文件传到插件,由它去停远端;
    - **回执与接着取**:插件的 `task` 事件落进 `Job.payload.remote_task`(和轮询循环同一格),重启后
      带着它调 `resume`,插件接着等,不再提交(ADR 0019);
    - 参数面依赖模型(每张工作流一套),不参与兜底 —— 描述符由插件目录给,存在模型行上。
    """

    supports_progress_callbacks = True
    supports_resume = True

    def __init__(self, package_id: str, media_kind: str) -> None:
        self.package_id = package_id
        self.vendor_id = vendor_for(package_id)
        self.media_kind = media_kind

    def requires_credentials(self) -> bool:
        return False

    def generate(
        self,
        request: GenerationRequest,
        context: GenerationAdapterContext,
        output_dir: Path,
        callbacks: GenerationProgressCallbacks | None = None,
    ) -> GenerationResult:
        return self._run(request, context, output_dir, callbacks, resume=None)

    def resume(
        self,
        poll_path: str,
        request: GenerationRequest,
        context: GenerationAdapterContext,
        output_dir: Path,
        callbacks: GenerationProgressCallbacks | None = None,
    ) -> GenerationResult:
        try:
            receipt = json.loads(poll_path)
        except ValueError:
            receipt = None
        if not isinstance(receipt, dict):
            raise GenerationAdapterError("providerErr_resumeUnsupported", vendor=self.vendor_id)
        return self._run(request, context, output_dir, callbacks, resume=receipt)

    def _run(
        self,
        request: GenerationRequest,
        context: GenerationAdapterContext,
        output_dir: Path,
        callbacks: GenerationProgressCallbacks | None,
        *,
        resume: dict[str, Any] | None,
    ) -> GenerationResult:
        hooks = StreamHooks(
            on_progress=(callbacks.on_progress if callbacks is not None else lambda _f, _m: None),
            # 回执经运行器装好的那一格落库(contracts.generation.remember_remote_task),
            # 和轮询型 Adapter 报的是同一格 —— 重启后运行器按同一个判据接着取。
            on_task=lambda task: remember_remote_task(json.dumps(task, ensure_ascii=False)),
            is_cancelled=(callbacks.is_cancelled if callbacks is not None else remote_task_cancelled),
        )
        inputs = tuple((item.role, _library_file(item.path)) for item in request.sources)
        call = plugin_generation.GenerationCall(
            model=request.model,
            kind=request.kind,
            prompt=request.prompt,
            negative_prompt=request.negative_prompt,
            parameters=dict(request.parameters),
            inputs=inputs,
            resume=resume,
        )
        with SessionLocal() as db:
            profile = db.get(ProviderProfile, context.connection_id) if context.connection_id else None
            if profile is None or not profile.plugin_instance_id:
                raise GenerationAdapterError("providerErr_pluginConnectionGone")
            try:
                outcome = plugin_generation.generate(
                    db, profile.plugin_instance_id, call, output_dir=output_dir, hooks=hooks
                )
            except PluginCancelled as exc:
                raise GenerationAdapterError("providerErr_cancelled") from exc
            except (PluginDomainError, PluginRuntimeError, LocalizedError) as exc:
                raise GenerationAdapterError("providerErr_pluginFailed", name=profile.name, detail=str(exc)) from exc
        usage = {**metering_from_request(request), **outcome.usage}
        return GenerationResult(output_paths=outcome.paths, usage=usage, raw_usage=outcome.raw)


def _library_file(path: Path) -> Path:
    """交给插件之前核对:**只交素材库里的文件**。

    执行器只会从本工作区的素材解析出这些路径(见 runner._sources_for_generation);这里再守一道,
    免得哪天有人往 GenerationRequest 里塞了一条别处的路径,而插件就把 `~/.ssh` 传去了 ComfyUI。
    和 host_files.asset_file 同一个判据:素材库的文件落在数据目录的媒体目录下。
    """
    real = path.resolve()
    root = settings.media_dir.resolve()
    if root not in real.parents:
        raise GenerationAdapterError("providerErr_pluginSourceNotLibrary", name=path.name)
    return real


def _adapter_source(vendor: str, kind: str) -> GenerationAdapter | None:
    """`ai/providers/registry` 的动态来源:`plugin:<包 id>` → 这家插件的 Adapter。

    不查库:有这个 vendor 的连接就说明包在(包 → 实例 → 连接一路外键级联),真跑起来时实例
    不在了会明确报「连接已不在」。
    """
    package_id = package_of(vendor)
    if not package_id or kind not in GENERATION_KINDS:
        return None
    return PluginGenerationAdapter(package_id, kind)


def install() -> None:
    """组装根调一次:登记宿主侧(实例变了就对齐连接)和 Adapter 的动态来源。"""
    host_capabilities.register(GENERATION, _handler, listing=provided_models)
    register_generation_adapter_source(_adapter_source)


__all__ = [
    "GENERATION_KINDS",
    "PluginGenerationAdapter",
    "VENDOR_PREFIX",
    "descriptor",
    "install",
    "package_of",
    "provided_models",
    "sync",
    "vendor_for",
]
