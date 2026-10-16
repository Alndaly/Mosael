"""整条动静曲线的落地:量出来的每个采样都留在素材目录里,不是算完就丢。

**为什么是文件,不是库里的 JSON 列。** 曲线是「5Hz × 时长」个数:200 秒 ≈ 1000 个,1 小时 ≈ 18000 个。
塞进 `shot_breakdowns` 的话,每次读镜头表(界面平时只读刀口和逐镜)都要把它整个搬一遍;而它和帧、联系表
是**同一类东西** —— 这份表量出来的中间产物,随素材目录生灭。所以它落在 `shots/track.json`
(`frames/`、`sheets/` 的同一层,一起进 `shots.new/` 再换),库里那一行只记 `{hz, points, digest}`。

**曲线是机器量到的事实,原样存**:不筛选、不补洞、不重采样、不做平滑。摘要取的是**文件原样的 sha256**
(谁动过它,读的时候一读就知道;对不上就当它不在,见 `read_track`)—— 这就是「机器证据」这四个字的全部内容。

**时间轴约定**:`values[i]` 是 `(i + 1) / hz` 秒处的帧间差,见 `detect.sample_time`。第 0 个采样不在
0 秒:ffmpeg 的 `tblend` 要前一帧,第 0 帧没有前一帧、不出值,所以整条曲线偏一帧。文件里把这条约定
写成 `timeline` 两个数,别让人去猜。
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.domain.shots import detect

#: 曲线在这份素材目录里的文件名(`shots/` 下,和 `frames/`、`sheets/` 同一层)。
TRACK_FILENAME = "track.json"


def track_file(shots_folder: Path) -> Path:
    """这份素材的曲线文件。`shots_folder` 是 `breakdowns.shots_dir(asset)`。"""
    return shots_folder / TRACK_FILENAME


def digest_of(data: bytes) -> str:
    """文件原样的摘要(`sha256:<hex>`)。库里记它、响应里带它,两头对上才说明这份曲线没被动过。"""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def encode(hz: int, duration: float, values: Sequence[float]) -> bytes:
    """曲线 → 文件字节。紧凑写(1 小时的曲线缩进写要 190 KB,紧凑写 100 KB 不到);**摘要取的就是这份字节**。"""
    payload = {
        "hz": int(hz),
        "duration": round(float(duration), 3),
        "points": len(values),
        "timeline": {"first_sample_seconds": round(detect.sample_time(0, hz), 6),
                     "sample_interval_seconds": round(1 / hz, 6)},
        "values": [float(value) for value in values],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def write_track(shots_folder: Path, *, hz: int, duration: float, values: Sequence[float]) -> dict[str, Any]:
    """把曲线写进 `shots_folder/track.json`,交回库里要留的那份摘要:`{hz, points, digest}`。

    一个采样都没有时**不落这份文件**(一条空的曲线不是曲线),交回 `{}` —— 库里那一栏留空,读的时候
    当成「没有曲线」。"""
    if not values:
        return {}
    data = encode(hz, duration, values)
    shots_folder.mkdir(parents=True, exist_ok=True)
    track_file(shots_folder).write_bytes(data)
    return {"hz": int(hz), "points": len(values), "digest": digest_of(data)}


def read_track(shots_folder: Path, *, expect_digest: str = "") -> dict[str, Any] | None:
    """读回整条曲线;文件不在、不是 JSON、形状不对、或者摘要对不上,一律回 `None`(调用方当它不在)。

    只有 `None` 一种失败 —— 调用方要区分「没量过」和「文件丢了」是问库里的摘要,不是问这里。
    """
    path = track_file(shots_folder)
    try:
        data = path.read_bytes()
    except OSError:
        return None
    digest = digest_of(data)
    if expect_digest and digest != expect_digest:
        return None
    try:
        payload = json.loads(data)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    hz = payload.get("hz")
    values = payload.get("values")
    if not isinstance(hz, int) or isinstance(hz, bool) or hz <= 0:
        return None
    if not isinstance(values, list) or not values:
        return None
    if payload.get("points") is not None and payload["points"] != len(values):
        return None
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
               for value in values):
        return None
    duration = payload.get("duration")
    return {
        "hz": hz,
        "points": len(values),
        "duration": float(duration) if isinstance(duration, (int, float)) and not isinstance(duration, bool) else 0.0,
        "first_sample_seconds": detect.sample_time(0, hz),
        "sample_interval_seconds": 1 / hz,
        "digest": digest,
        "values": [float(value) for value in values],
    }


__all__ = ["TRACK_FILENAME", "digest_of", "encode", "read_track", "track_file", "write_track"]
