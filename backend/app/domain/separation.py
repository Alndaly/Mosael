"""把一份素材拆成人声和伴奏两份素材。

**这一层是"能力"和"素材"之间的那道缝**(ADR-0016):上面的调用方(工作流节点、配音流程、
以后的剪辑台和 MCP)只跟这里说话,不认识任何一个引擎;下面由 `providers.registry` 决定
这次用哪个 Adapter。所以加一个引擎不需要改这里,而这里改了也不会波及某个引擎。

两条硬规矩:

- **产出新素材,不就地改原素材。** 原片一个字节都不动,拆出来的是两份新的音频素材。
  和配音同一条原则:不删任何东西,所以每一步都能靠"删掉新加的"回退。
- **可用性是问出来的。** `available()` 不读配置,它问注册表里有没有现在就跑得起来的引擎。
  问不到时调用方退回没有这个能力的做法 —— 而不是先调一次再看报错,那一次可能已经等了十分钟。
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.ai.providers.contracts.separation import (
    ACCOMPANIMENT,
    VOCALS,
    SeparationError,
    SeparationRequest,
)
from app.ai.providers.registry import get_separation_adapter
from app.db.models import Asset
from app.domain.assets.importer import register_file_asset

logger = logging.getLogger(__name__)

#: 拆出来的两份素材,名字后面缀什么。取名要让人在素材库里一眼认出它是从哪儿来的。
_SUFFIX = {VOCALS: "人声", ACCOMPANIMENT: "伴奏"}


@dataclass(frozen=True)
class SeparatedAssets:
    """一次分离的产出。两份都是**新的**素材行。"""

    vocals: Asset
    accompaniment: Asset
    engine: str


def available(engine: str = "") -> bool:
    """现在有没有跑得起来的分离引擎。"""
    adapter = get_separation_adapter(engine)
    return bool(adapter and adapter.runtime_ready())


def separate_asset(
    db: Session,
    asset: Asset,
    *,
    engine: str = "",
    project_id: str | None = None,
) -> SeparatedAssets:
    """把这份素材拆成人声 + 伴奏两份新素材。

    输入可以是视频:分离引擎只认音频,所以先抽一条 wav 出来 —— 走的是转写那条现成的路
    (`voices.transcription._extract_audio`),不另写一份 ffmpeg 调用。
    """
    adapter = get_separation_adapter(engine)
    if adapter is None:
        raise SeparationError("没有可用的音频分离引擎")
    if not adapter.runtime_ready():
        # 装是显式的一步:第一次要建 venv、装 torch、拉权重,那是几分钟到几十分钟的事,
        # 不该藏在"点一下分离"后面一声不响地发生。
        adapter.ensure_runtime()

    source = _source_path(asset)
    if source is None or not source.is_file():
        raise SeparationError("这份素材的文件找不到了")

    with tempfile.TemporaryDirectory(prefix="mosael-separate-") as tmp:
        work = Path(tmp)
        audio = _as_audio(source, work)
        stems = adapter.separate(SeparationRequest(audio_path=audio), work / "out")
        made: dict[str, Asset] = {}
        for stem in (VOCALS, ACCOMPANIMENT):
            path = stems.get(stem)
            if path is None or not path.is_file():
                raise SeparationError(f"分离结果里缺少:{_SUFFIX[stem]}")
            made[stem] = register_file_asset(
                db,
                workspace_id=asset.workspace_id,
                project_id=project_id or asset.project_id,
                source_path=path,
                name=f"{asset.name} · {_SUFFIX[stem]}",
                source="separated",
            )
    return SeparatedAssets(vocals=made[VOCALS], accompaniment=made[ACCOMPANIMENT], engine=adapter.engine_id)


def _source_path(asset: Asset) -> Path | None:
    """素材的本机文件。走 `file_key` + resolve_key —— 转写那条路也是这么问的,
    而 Asset 上并没有一个现成的 `path` 字段(顶层那几个常见字段其实住在 media_info 里)。"""
    from app.media.paths import resolve_key

    if not asset.file_key:
        return None
    return resolve_key(asset.file_key)


def _as_audio(source: Path, work: Path) -> Path:
    """视频先抽音频;本来就是音频的原样用。"""
    if source.suffix.lower() in {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}:
        return source
    from app.domain.voices.transcription import _extract_audio

    target = work / "source.wav"
    _extract_audio(source, target)
    return target
