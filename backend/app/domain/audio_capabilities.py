"""降噪、分离人声是两项宿主能力(ADR 0032 第二步):本地引擎是内置提供方,插件连接和它们并列。

此前两族引擎是进程全局的注册表(`ai/providers/registry.DENOISE_ADAPTERS` / `SEPARATION_ADAPTERS`),节点里写死
`auto / ffmpeg / deepfilternet / rnnoise`、`auto / demucs`,插件插不进来。现在:

- **挑哪一家**走能力表那一份挑法(`capabilities.pick`):节点、画板、智能体、素材库点名的是提供方 id(内置的是
  `builtin:<引擎>`,插件的是连接 id);不点名按这个人的默认,没定默认用第一个允许自动、跑得起来的内置引擎 ——
  降噪里会顺手去掉配乐的语音模型不自动用;
- **契约**(认领 `audio_denoise` / `audio_separation` 的工具是一个普通工具,ADR 0033):
  - 入:`file` 是一段声音(`format: asset`,`x-media` 含 audio 与 video,`x-audio: original` —— 宿主先抽成原采样率的
    wav 再给);可选 `filename`(原素材名),降噪多一个 `strength`:light|medium|strong;
  - 出:降噪 `{"artifact": {"path": …}}`,分离 `{"artifacts": [{"path": …, "output": "vocals"}, {…, "output": "background"}]}`
    —— 和别的工具交文件同一个写法;
  - 进度、取消和别的流式工具同一套(NDJSON 进度行、`MOSAEL_PLUGIN_CANCEL_FILE`)。
  宿主的入口(素材库的降噪 / 分离、节点、画板)调它时,产出在暂存目录删之前由入口取走,放回视频、登记成新素材都是
  入口的事(domain/assets/denoise、domain/assets/separation);智能体、工作流直接调它时,产出按通用规矩进素材库。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.ai.providers.contracts.denoise import STRENGTHS, DenoiseAdapter, DenoiseError, DenoiseRequest
from app.ai.providers.contracts.separation import BACKGROUND, VOCALS, SeparationAdapter, SeparationError, SeparationRequest
from app.ai.providers.registry import DENOISE_ADAPTERS, SEPARATION_ADAPTERS
from app.core.i18n import tr
from app.domain import capabilities
from app.domain.capabilities import Builtin, Capability, CapabilityUnavailable, Provider
from app.domain.plugins.manifest import AUDIO_DENOISE, AUDIO_SEPARATION

BUILTIN_PREFIX = "builtin:"


class DenoiseProviderUnavailable(CapabilityUnavailable, DenoiseError):
    """挑不出能用的降噪实现。仍是 DenoiseError —— 降噪的调用方照样接得住。"""


class SeparationProviderUnavailable(CapabilityUnavailable, SeparationError):
    """挑不出能用的分离实现。仍是 SeparationError。"""


def _ready(adapter: Any, hint_key: str, fallback_key: str):
    def missing(_db: Session, _owner: str | None) -> tuple[str, ...]:
        if adapter.runtime_ready():
            return ()
        return (tr(hint_key) if hint_key else tr(fallback_key, engine=adapter.engine_id),)

    return missing


DENOISE = Capability(
    name=AUDIO_DENOISE,
    label_key="capability_audio_denoise",
    description_key="capability_audio_denoise_desc",
    error=DenoiseProviderUnavailable,
    none_key="denoiseErr_noEngine",
    unknown_key="denoiseErr_unknownEngine",
    builtins=tuple(
        Builtin(id=f"{BUILTIN_PREFIX}{adapter.engine_id}", name_key=adapter.label_key,
                ready=_ready(adapter, adapter.setup_hint_key, "denoiseErr_engineNotReady"),
                automatic=not adapter.removes_music)
        for adapter in DENOISE_ADAPTERS.values()
    ),
    #: 声音交给插件(多半是云端)必须是他自己定过的,不替他挑。
    auto_single=False,
)

SEPARATION = Capability(
    name=AUDIO_SEPARATION,
    label_key="capability_audio_separation",
    description_key="capability_audio_separation_desc",
    error=SeparationProviderUnavailable,
    none_key="separationErr_noEngine",
    unknown_key="separationErr_unknownEngine",
    #: demucs 第一次用时由宿主装好(见 separation.separate_asset),所以它总在候选里、不报缺什么。
    builtins=tuple(Builtin(id=f"{BUILTIN_PREFIX}{adapter.engine_id}", name_key=adapter.label_key)
                   for adapter in SEPARATION_ADAPTERS.values()),
    auto_single=False,
)


def _produced(scratch: Path, spec: Any, error: type[Exception], key: str) -> Path:
    """插件交回的一份 `artifact` → 暂存目录里那份文件;没交、交在外面都说清楚。"""
    from app.domain.plugins.tools import staged_artifact

    found = staged_artifact(scratch, spec)
    if found is None:
        raise error(key, detail=str(spec)[:200])
    return found


class PluginDenoiseAdapter:
    """把认领 `audio_denoise` 的插件工具包成一个降噪适配器 —— 调用方不关心背后是本地引擎还是插件。"""

    removes_music = False
    setup_hint_key = ""
    strengths = STRENGTHS

    def __init__(self, provider: Provider) -> None:
        self.engine_id = provider.id
        self.label_key = provider.name
        self.description_key = ""
        self._provider = provider

    def runtime_ready(self) -> bool:
        return not self._provider.missing

    def denoise(self, request: DenoiseRequest, out_path: Path) -> Path:
        from app.core.db import SessionLocal
        from app.domain.plugins.errors import PluginDomainError
        from app.domain.plugins.runtime import PluginRuntimeError
        from app.domain.plugins.tools import invoke_host, quiet_hooks

        def collect(output: dict[str, Any], scratch: Path) -> dict[str, Any]:
            produced = _produced(scratch, output.get("artifact"), DenoiseError, "denoiseErr_pluginBadOutput")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(produced, out_path)
            return {"artifact": produced.name}

        try:
            with SessionLocal() as db:
                invoke_host(db, self._provider.id, AUDIO_DENOISE,
                            {"filename": request.audio_path.name, "strength": request.strength},
                            files={"file": request.audio_path}, collect=collect, hooks=quiet_hooks())
        except (PluginDomainError, PluginRuntimeError) as exc:
            raise DenoiseError("denoiseErr_pluginFailed", plugin=self._provider.name, detail=str(exc)[:500]) from exc
        return out_path


class PluginSeparationAdapter:
    """把认领 `audio_separation` 的插件工具包成一个分离适配器。"""

    def __init__(self, provider: Provider) -> None:
        self.engine_id = provider.id
        self.label_key = provider.name
        self._provider = provider

    def runtime_ready(self) -> bool:
        return not self._provider.missing

    def ensure_runtime(self) -> None:
        return None

    def separate(self, request: SeparationRequest, out_dir: Path) -> dict[str, Path]:
        from app.core.db import SessionLocal
        from app.domain.plugins.errors import PluginDomainError
        from app.domain.plugins.runtime import PluginRuntimeError
        from app.domain.plugins.tools import invoke_host, quiet_hooks

        made: dict[str, Path] = {}

        def collect(output: dict[str, Any], scratch: Path) -> dict[str, Any]:
            out_dir.mkdir(parents=True, exist_ok=True)
            specs = output.get("artifacts") if isinstance(output.get("artifacts"), list) else []
            for stem in (VOCALS, BACKGROUND):
                spec = next((one for one in specs if isinstance(one, dict) and one.get("output") == stem), None)
                produced = _produced(scratch, spec, SeparationError, "separationErr_pluginBadOutput")
                target = out_dir / f"{stem}{produced.suffix or '.wav'}"
                shutil.copyfile(produced, target)
                made[stem] = target
            return {stem: made[stem].name for stem in (VOCALS, BACKGROUND)}

        try:
            with SessionLocal() as db:
                invoke_host(db, self._provider.id, AUDIO_SEPARATION, {"filename": request.audio_path.name},
                            files={"file": request.audio_path}, collect=collect, hooks=quiet_hooks())
        except (PluginDomainError, PluginRuntimeError) as exc:
            raise SeparationError("separationErr_pluginFailed", plugin=self._provider.name, detail=str(exc)[:500]) from exc
        return made


def denoise_adapter(db: Session, owner_user_id: str | None, provider_id: str | None) -> DenoiseAdapter:
    """这一次用哪一家降噪:点名的,或按默认挑。挑不出来抛一句说清下一步的话。"""
    provider = capabilities.pick(db, owner_user_id, DENOISE, provider_id or None)
    if provider.builtin:
        return DENOISE_ADAPTERS[provider.id.removeprefix(BUILTIN_PREFIX)]
    return PluginDenoiseAdapter(provider)


def separation_adapter(db: Session, owner_user_id: str | None, provider_id: str | None) -> SeparationAdapter:
    provider = capabilities.pick(db, owner_user_id, SEPARATION, provider_id or None)
    if provider.builtin:
        return SEPARATION_ADAPTERS[provider.id.removeprefix(BUILTIN_PREFIX)]
    return PluginSeparationAdapter(provider)


def register_uses() -> None:
    """宿主界面上用到这两项能力的入口(ADR 0032 §4)。工作流节点、智能体工具由各自注册表现扫。"""
    from app.core.i18n import fragment
    from app.domain.capabilities import Use, register_use

    register_use(Use(AUDIO_DENOISE, "app", fragment("capUse_assetDenoise")))
    register_use(Use(AUDIO_SEPARATION, "app", fragment("capUse_assetSeparate")))


__all__ = [
    "register_uses",
    "BUILTIN_PREFIX",
    "DENOISE",
    "SEPARATION",
    "DenoiseProviderUnavailable",
    "PluginDenoiseAdapter",
    "PluginSeparationAdapter",
    "SeparationProviderUnavailable",
    "denoise_adapter",
    "separation_adapter",
]
