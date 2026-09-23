"""发出去的那一条作品:平台上的作品 ID、链接、发布时间。

## 为什么要记

「发布成功」只说明点了发布、平台收下了。之后要查**这一条**作品的播放、点赞、评论
(TikHub 之类的接口都是按作品 ID 取:抖音 / TikTok 的 aweme_id、B 站的 bvid、
小红书的 note_id、YouTube 的 video_id),得先知道它在平台上叫什么。发的时候不记,
事后只能拿标题去平台上猜 —— 同名的、改过标题的、被平台截断的,都猜不准。

## 从哪来

ID 是执行器(electron/publish)在点「发布」那一刻从**平台自己的发布接口的返回**里读的
(见 electron/publish/publishedPost.ts),平台的前端拿到的就是这个 ID。读不到(平台改了
接口)时 `post_id` 是空串 —— **不编一个**:空的一眼看得出没抓到,编的会被当真去查。

## 形状

    {"platform": "bilibili", "post_id": "BV1xx411c7mD", "url": "https://www.bilibili.com/video/BV1xx411c7mD",
     "ids": {"bvid": "BV1xx411c7mD", "aid": "170001"}, "published_at": "2026-09-23T08:00:00Z"}

`ids` 是接口返回里认得出的**全部**标识(有的平台一条作品有两个 ID,不同的查询接口要的不一样)。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

#: 单个标识的上限。平台的作品 ID 都在几十个字符以内;更长的多半是读错了字段。
_ID_MAX = 128
_ID_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")
_IDS_MAX = 12


def _text(value: Any, limit: int) -> str:
    return str(value).strip()[:limit] if isinstance(value, (str, int)) and not isinstance(value, bool) else ""


def published_post(platform: str, reported: dict[str, Any] | None, *, at: datetime) -> dict[str, Any]:
    """执行器报上来的作品信息 → 存进任务的那一份。

    报上来的东西来自一个浏览器页面,所以**逐项收窄**:链接只认 http(s),标识只收短字符串,
    键名只认标识符的样子。报了什么都没有时,也照样记下平台和发布时间 —— 那是确定的。
    """
    reported = reported if isinstance(reported, dict) else {}
    url = _text(reported.get("url"), 500)
    if not url.startswith(("https://", "http://")):
        url = ""
    raw_ids = reported.get("ids") if isinstance(reported.get("ids"), dict) else {}
    ids: dict[str, str] = {}
    for key, value in raw_ids.items():
        text = _text(value, _ID_MAX)
        if isinstance(key, str) and _ID_KEY.match(key) and text:
            ids[key] = text
        if len(ids) >= _IDS_MAX:
            break
    return {
        "platform": platform,
        "post_id": _text(reported.get("post_id"), _ID_MAX),
        "url": url,
        "ids": ids,
        "published_at": at.replace(microsecond=0).isoformat() + "Z",
    }
