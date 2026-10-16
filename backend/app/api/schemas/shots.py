"""镜头表(ADR 0061 §5)的对外形状。

**一份视频一份**(`shot_breakdowns`,`asset_id` 唯一);没拆过不是 404,是一次正常的回答(见 `status`)。
逐镜的字段不在这里再声明一遍:它们是 `domain/shots` 存下来的那份 JSON,形状(镜号、起止、时长、动静、
景别、运镜、转场、节奏、画面、分镜提示词、台词……)由那个领域定,这里只把它原样交出去。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.api.schemas.base import ApiModel


class ShotBreakdownResponse(ApiModel):
    """读一份视频的镜头表。**没拆过也是 200**:`status="none"`,其余几栏是空的。

    和同一份素材上的 `AnalyzeAssetResponse` 同一类:它是一次回答,不是一行 ORM(`*Out` 那一族)。
    """

    asset_id: str
    #: none = 还没拆过(其余几栏为空),ready = 有镜头表。
    status: Literal["none", "ready"]
    id: str = ""
    #: 判画面用哪种语言写的(zh / en)。
    lang: str = ""
    #: 量刀口用的参数:`threshold`、`min_shot`。
    params: dict[str, Any] = Field(default_factory=dict)
    #: 探测得来的:`duration`、`fps`、`width`、`height`、`has_audio`。
    meta: dict[str, Any] = Field(default_factory=dict)
    #: 逐镜。每镜的字段见 domain/shots:`id` / `start` / `end` / `seconds` / `motion`(代码量的),
    #: `size` / `category` / `camera` / `transition_in` / `rhythm` / `frame` / `prompt` / `dialogue`(模型判的 + 代码分的台词)。
    shots: list[dict[str, Any]] = Field(default_factory=list)
    #: 整条动静曲线的摘要:`{hz, points, digest}`。**曲线本体不在这里**(5Hz × 时长 个数 —— 1 小时就是
    #: 一万八千个数,读一次镜头表不该把它整个搬过来),走 `GET /assets/{id}/shots/track`。没有曲线是 `{}`。
    motion_track: dict[str, Any] = Field(default_factory=dict)
    #: 联系表:`[{index, first, last, a, b}]`(`a` / `b` 是 `shots/sheets/` 下的文件名)。
    sheets: list[dict[str, Any]] = Field(default_factory=list)
    #: 谁判的画面:`{provider, model, batches, judged_batches, error}`;一镜都没判过是空的。
    describe: dict[str, Any] = Field(default_factory=dict)
    #: 对账和节奏的提示 `[{shot, kind, field, value}]`,界面按 `kind` 翻成一句话。
    hints: list[dict[str, Any]] = Field(default_factory=list)
    #: 代码算的统计(平均镜长、每分钟几刀、景别 / 运镜分布)。
    stats: dict[str, Any] = Field(default_factory=dict)
    #: 镜头表 Markdown(存笔记用)。
    report_markdown: str = ""
    #: 分镜提示词 Markdown(「复制分镜提示词」按钮用的就是它)。
    storyboard_markdown: str = ""
    updated_at: datetime | None = None


class ShotMotionTrackResponse(ApiModel):
    """一条视频的**整条**动静曲线(5Hz 的每个采样),机器证据那一份。

    **时间轴约定:`values[i]` 是 `(i + 1) / hz` 秒处的帧间差**(0–255 的 YAVG,见 detect.sample_time)。
    第 0 个采样不在 0 秒:ffmpeg 的 `tblend` 算的是「这一帧和前一帧的差」,第 0 帧没有前一帧、不出值,
    所以序列的第 0 个值其实是原视频的第 1 帧(5Hz 下是 0.2 秒处)。`first_sample_seconds` 和
    `sample_interval_seconds` 把这条约定写成数,前端照着画:第 i 个点在 `first + i × interval` 秒。

    **不做平滑、不补洞、不降采样** —— 降采样是画法(节奏条几百像素宽,画的人自己抽),不是事实。
    刀口不在这里重复一遍:它在 `GET /assets/{id}/shots` 的 `shots[].start` / `end`(每镜的起止就是刀口)。

    **没有曲线也是 200**:`status` 说清是哪一种(和读镜头表同一个态度,见 `ShotBreakdownResponse`)。
    """

    asset_id: str
    #: none = 没有量过(或这一版之前的行没记)、ready = 有、missing = 库里记着但盘上那份丢了或被人动过(重拆一次就有)。
    status: Literal["none", "ready", "missing"]
    #: 采样率(Hz):曲线每秒几个点。今天恒为 5(`detect.MOTION_HZ`),以后调了前端照这个数读。
    hz: int = 0
    #: 采样点数 = `len(values)`;`missing` 时是当初记下的点数。
    points: int = 0
    #: 曲线覆盖的时长(秒,探测得来的)。
    duration: float = 0.0
    #: 第 0 个采样落在第几秒 = `1 / hz`。
    first_sample_seconds: float = 0.0
    #: 相邻两个采样差几秒 = `1 / hz`。
    sample_interval_seconds: float = 0.0
    #: `shots/track.json` **文件原样**的 sha256(`sha256:<hex>`):两头对得上才说明这条曲线没被动过。
    digest: str = ""
    #: 整条曲线,原样。`values[i]` 在 `(i + 1) / hz` 秒处;`ready` 之外是空的。
    values: list[float] = Field(default_factory=list)


__all__ = ["ShotBreakdownResponse", "ShotMotionTrackResponse"]
