"""模板里的「成片配乐」那几步:生成一首 → (会唱的模型)只留伴奏 → 内容铺好之后、导出之前铺到时间线上。

带货口播先有(ADR 0095),整片(漫剧这类多场景的片子)也要 —— 两处搭的是同一组节点,只是「哪条时间线、写好什么就
开始生成、接在哪一步导出前面、曲子写成什么样」不同。所以在这里做一次,模板各自给这几样。

怎么铺(从头铺到末尾、按响度垫底、有人说话时再压低、曲子短了首尾接着铺)在 `sequences.background_music`;这里只管
图上的节点和连线。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.domain.workflows.templates.model_choice import ModelChoice, model_capabilities, music_request


@dataclass(frozen=True)
class BackgroundMusic:
    """配乐用哪个模型、要不要先拆掉人声。

    `strip_vocals`:这个模型交回来的可能带人声(见 templates/model_choice.music_may_sing)—— 写法管不住它会不会唱,
    生成之后先拆一遍人声、只铺伴奏。挑模型在 templates._background_music(要查这台机器的分离引擎)。
    """

    model: ModelChoice
    strip_vocals: bool = False


@dataclass(frozen=True)
class MusicSlot:
    """配乐那几步在某个模板里接在哪。

    - `description`:曲子写成什么样(英文,可以引用上游,比如片名、基调);
    - `seconds`:要多长 —— 只是上限,模型给的长度不可控,短了铺的时候首尾接着铺;
    - `sequence_id`:铺到哪条时间线(引用);
    - `starts_after`:哪一步做完就开始生成(和后面的出图、出视频同时跑);
    - `export_node`:导出那一步的 id —— 原来接到它的那条线改成先接配乐、再导出(配乐按「内容铺好那一刻」的末尾截);
    - `origin`:画布上从哪摆起(三张卡片往右排)。
    """

    description: str
    seconds: int
    sequence_id: str
    starts_after: str
    export_node: str
    origin: tuple[int, int]


def add_background_music(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]], music: BackgroundMusic | None, slot: MusicSlot,
    db: Session | None,
) -> None:
    """把配乐那几步加进图里(`music` 是 None 就什么都不加)。官网导出的那份不带(模型是空的,导入的人得先删掉它们才跑得起来)。"""
    if music is None or not music.model.model:
        return
    model = music.model
    #: 曲子写在哪、歌词怎么空着、时长写进哪一格,见 music_request。
    prompt, parameters = music_request(model_capabilities(db, model, "audio"), slot.description, seconds=slot.seconds)
    x, y = slot.origin
    nodes.extend([
        {
            "id": "bgm_music",
            "type": "ai_generate",
            "name": {"zh": "生成一首配乐", "en": "Generate the background music"},
            "position": {"x": x, "y": y},
            "config": {
                "provider": model.provider, "provider_profile_id": model.profile_id, "model": model.model,
                "kind": "audio", "prompt": prompt,
                "parameters": parameters,
            },
        },
        {
            "id": "bgm_lay",
            "type": "timeline_background_music",
            "name": {"zh": "铺上配乐", "en": "Lay the background music"},
            "position": {"x": x + 710, "y": y},
            "config": {"sequence_id": slot.sequence_id,
                       "asset_id": "{{bgm_backing.background_asset_id}}" if music.strip_vocals else "{{bgm_music.asset_id}}"},
        },
    ])
    if music.strip_vocals:
        nodes.append({
            "id": "bgm_backing",
            "type": "separate_audio",
            "name": {"zh": "配乐只留伴奏", "en": "Keep only the music's backing"},
            "position": {"x": x + 350, "y": y},
            "config": {"asset_id": "{{bgm_music.asset_id}}"},
        })
        edges.append({"id": "music_backing", "source": "bgm_music", "target": "bgm_backing"})
    into_export = next(edge for edge in edges if edge["target"] == slot.export_node)
    edges.remove(into_export)
    edges.extend([
        {"id": "starts_music", "source": slot.starts_after, "target": "bgm_music"},
        {"id": "music_lay", "source": "bgm_backing" if music.strip_vocals else "bgm_music", "target": "bgm_lay"},
        {"id": "content_lay", "source": into_export["source"], "target": "bgm_lay"},
        {"id": "lay_export", "source": "bgm_lay", "target": slot.export_node},
    ])


__all__ = ["BackgroundMusic", "MusicSlot", "add_background_music"]
