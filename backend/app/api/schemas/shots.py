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


__all__ = ["ShotBreakdownResponse"]
