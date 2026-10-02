"""一条时间线现在长什么样 —— 智能体的 inspect_sequence 和工作流的「看一眼时间线」读的是同一份。

此前两边各写一份,而且各错各的:智能体那份把片段时长算成 `src_out - src_in`(源时长,2 倍速的片段在那儿
长了一倍,总时长跟着错),不给 src_in / src_out / speed,看不出哪段已经静音、哪条轨在闪避,也分不出
脱机片段和字幕条(两者 asset 都是空);工作流那份按速度算对了时长,却不带字幕的文字。照着这样的视图下单,
模型算出来的切点和落点本来就是错的。
"""

from __future__ import annotations

from typing import Any

from app.db.models import Clip, Sequence, Track
from app.domain.sequences._timeline import timeline_span


def describe_sequence(sequence: Sequence) -> dict[str, Any]:
    """时长都是**时间线上**的(按速度算);src_in / src_out 是素材里的时间 —— 切点、裁剪按它说。"""
    tracks = sorted(sequence.tracks, key=lambda track: track.position)
    rows = [_track(track) for track in tracks]
    duration = max(
        (clip.timeline_start + timeline_span(clip) for track in tracks for clip in track.clips), default=0.0
    )

    def first(kind: str) -> str:
        # 顺手把第一条视频 / 音频轨的 id 摆出来 —— 「接素材」想指定轨道时不用自己去 tracks 里翻。
        return next((track.id for track in tracks if track.kind == kind), "")

    return {
        "sequence_id": sequence.id,
        "name": sequence.name,
        "width": sequence.width,
        "height": sequence.height,
        "fps": sequence.fps,
        "revision": sequence.revision,
        "duration": round(duration, 3),
        "video_track_id": first("video"),
        "audio_track_id": first("audio"),
        "tracks": rows,
    }


def _track(track: Track) -> dict[str, Any]:
    row: dict[str, Any] = {"track_id": track.id, "name": track.name, "kind": track.kind}
    if track.role:
        row["role"] = track.role
    if track.kind == "subtitle":
        row["hidden"] = track.hidden
    else:
        row.update(muted=track.muted, solo=track.solo, duck=track.duck)
    row["locked"] = track.locked
    row["clips"] = [_clip(clip) for clip in track.clips]
    return row


def _clip(clip: Clip) -> dict[str, Any]:
    row: dict[str, Any] = {
        "clip_id": clip.id,
        "timeline_start": round(clip.timeline_start, 3),
        "duration": round(timeline_span(clip), 3),
    }
    if clip.asset is not None:
        row.update(asset_id=clip.asset_id, asset=clip.asset.name)
        # 含 AI 生成内容(素材登记时定下、顺着出处继承的那一列):导出会加「AI 生成」标识,模型要能说得出是哪几段。
        # 读的是素材行上的一列,不经素材域的函数 —— 序列域不 import 素材域(素材删除要回头动片段,反过来就成环)。
        if clip.asset.ai_generated:
            row["ai_generated"] = True
    elif clip.offline:
        # 素材被删了:这一段还在时间线上,但导出会被挡住。名字要给出来,模型才能告诉用户缺的是哪个文件。
        row.update(offline=True, asset=str((clip.offline_asset or {}).get("name") or ""))
    if clip.asset is not None or clip.offline:
        row.update(src_in=clip.src_in, src_out=clip.src_out, speed=clip.speed or 1.0, gain=clip.gain, muted=clip.muted)
    # 链接组(画面和分离出去的音频):挪、修剪、切、删、变速默认整组一起动(见 sequences/links)。
    # 不给出来,模型挪一段画面时不知道另一条轨上的音频会跟着走。
    if clip.link_group:
        row["link_group"] = clip.link_group
    # 字幕条没有素材,它的内容就是那行字;花字片段同样。不给出来,模型既看不出写的是什么,也没法说「把这几条改一下」。
    text = str(clip.text_override or "").strip()
    if text:
        row["text"] = text
    return row
