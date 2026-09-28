"""批量翻译(字幕、文案)的出入参。领域在 domain/translate.py。"""

from __future__ import annotations

from pydantic import Field

from app.api.schemas.base import ApiModel


class TranslateRequest(ApiModel):
    #: 这次翻译算在哪个工作区头上。以前没有这个字段 —— 于是这个接口回答不了「这笔钱算谁的」,
    #: 而用量表的 workspace_id 是 NOT NULL,AI 翻译因此一条账都记不了。补的是建模缺失,
    #: 不是一道闸门:它同时把这个接口纳入了工作区权限体系。
    workspace_id: str
    #: 一次请求的条数上限。这是**防止一次请求打垮自己**的安全阀,不是「能翻多少字幕」的答案 ——
    #: 一条一小时视频的字幕轨轻松上千条。分批在客户端做(见 frontend/src/api/domains/editor.translateTexts,
    #: 那是唯一出口),所以这里不必为了迁就轨道长度把它调大:每一批都在这个数以内。
    texts: list[str] = Field(min_length=1, max_length=500)
    target_lang: str
    #: 翻译提供方 id(`builtin:google`、`builtin:chat`、插件连接 id);空 = 按这个人的默认(ADR 0032)。
    engine: str = ""
    profile_id: str | None = None


class TranslateResponse(ApiModel):
    translations: list[str]
