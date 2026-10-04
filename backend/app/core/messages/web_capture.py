"""浏览器会话顶栏的页面工具报给用户的话。"""

from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    "webCaptureErr_kind": {
        "zh": "不认得这种截取方式「{kind}」。",
        "en": "Unknown capture type “{kind}”.",
    },
    "webCaptureErr_pageUrl": {
        "zh": "来源网址必须是 http(s) 地址。",
        "en": "The source page must be an http(s) address.",
    },
    "webCaptureErr_sourceUrl": {
        "zh": "图片地址必须是 http(s) 地址。",
        "en": "The image address must be an http(s) address.",
    },
    "webCaptureErr_capturedAt": {
        "zh": "截取时间不是有效的时间。",
        "en": "The capture time isn't a valid timestamp.",
    },
    "webCaptureErr_notImage": {
        "zh": "这份文件不是图片(只收 PNG、JPEG、GIF、WebP、AVIF)。",
        "en": "This file isn't an image (PNG, JPEG, GIF, WebP and AVIF are accepted).",
    },
    "webCaptureErr_tooLarge": {
        "zh": "文件太大了:最多 {max_mb} MB。",
        "en": "The file is too large: {max_mb} MB at most.",
    },
    "pageNoteErr_empty": {
        "zh": "这一页没有读出正文,也没有选中文字。",
        "en": "No article text could be read from this page, and no text is selected.",
    },
    "pageNoteTitle_selection": {
        "zh": "{title}(摘录)",
        "en": "{title} (excerpt)",
    },
    "pageNoteFrom": {
        "zh": "来源:[{title}]({url})",
        "en": "Source: [{title}]({url})",
    },
}
