"""一次失败(生成、画板格子上跑的能力)给人看的那**一句话**。原文(上游回包、httpx 的原话)另放,在「查看原始错误」里。

此前这句话由各个界面自己从原文里抠:画板格子把原文截三行原样贴出来(一串英文加带签名的地址),AI 工作台用正则
找回包里的 message、再按「 For more information check:」切掉 httpx 的尾巴 —— 而 httpx 那里是换行不是空格,切不掉。
同一个失败(Key 填错)两页两种说法,哪一页都没告诉用户该去哪改(UC-06)。

现在只在这里产出:
- 带文案 key 的失败,照 key 翻;笼统的「{vendor} 请求失败」(`providerErr_requestFailed`)按 HTTP 状态码归到已有的
  几类(密钥不对 / 余额不足 / 限流 / 参数不对 / 服务不可用,见 ai/providers/contracts/failures)——
  用户一眼知道下一步是换钥匙、充值、等一会儿还是改参数;
- 句子里那段上游原文(`detail`)只留**服务商自己说的那句**(回包 JSON 里的 message),没有就去掉 httpx 的套话、
  地址和「For more information check」那截尾巴,截到一句话的长度;
- 没有 key 的(第三方原话)同样只做这一步清理。

不翻、不猜上游的原话,只是不把它整段搬到用户眼前。
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.ai.providers.contracts.failures import UPSTREAM_ERROR_KEYS, http_status_category
from app.core.i18n import is_message_key, t

#: 摘要里那段上游原话最长多少字。再长就是原文了 —— 原文在「查看原始错误」里。
SUMMARY_DETAIL_CHARS = 160

#: httpx 状态码异常的原话:`Client error '401 Unauthorized' for url 'https://…'` 加一行
#: `For more information check: https://developer.mozilla.org/…`。
_HTTPX_STATUS = re.compile(r"\b(?:Client|Server|Informational|Redirect) error '(\d{3})[^']*'")
_HTTPX_PREFIX = re.compile(r"\b(?:Client|Server|Informational|Redirect) error '(\d{3} [^']*)'")
_FOR_URL = re.compile(r"\s*for url '[^']*'")
_MORE_INFO = re.compile(r"\s*For more information check:.*", re.DOTALL)
_BODY = re.compile(r";\s*body:\s*(.*)$", re.DOTALL)
_URL = re.compile(r"https?://\S+")
_HTTP_STATUS = re.compile(r"\bHTTP (\d{3})\b")


def summarize(error: str | None, key: str, params: dict[str, Any] | None, locale: str) -> str:
    """一次失败给人看的那一句话(按 `locale` 翻)。`error` 是原文,`key` / `params` 是它的文案 key 与参数(没有就是空)。"""
    if key and is_message_key(key):
        fields = dict(params or {})
        detail = fields.get("detail")
        if isinstance(detail, str) and detail.strip():
            if key == "providerErr_requestFailed":
                status = status_of(detail)
                category = http_status_category(status) if status else None
                if category in UPSTREAM_ERROR_KEYS:
                    key = UPSTREAM_ERROR_KEYS[category]
            fields["detail"] = short_detail(detail)
        return t(key, locale, **fields)
    return short_detail(error or "")


def status_of(text: str) -> int | None:
    """原文里的 HTTP 状态码(httpx 的原话,或者我们自己写的「HTTP 403」);没有就是 None。"""
    found = _HTTPX_STATUS.search(text) or _HTTP_STATUS.search(text)
    return int(found.group(1)) if found else None


def short_detail(text: str) -> str:
    """上游原文 → 摘要里那一小段:服务商回包里自己说的那句;没有就是去掉套话、地址和尾巴之后的头一句。"""
    raw = str(text or "").strip()
    if not raw:
        return ""
    body = _BODY.search(raw)
    if body:
        spoken = _provider_message(body.group(1))
        if spoken:
            return _clip(spoken)
        raw = raw[: body.start()]
    raw = _MORE_INFO.sub("", raw)
    raw = _FOR_URL.sub("", raw)
    raw = _HTTPX_PREFIX.sub(lambda found: f"HTTP {found.group(1)}", raw)
    raw = _URL.sub("", raw)
    return _clip(raw)


def _provider_message(body: str) -> str:
    """回包 JSON 里服务商自己写给人看的那句:`error.message` / `message` / `msg`,再不行是错误码。读不懂就是空。"""
    try:
        payload = json.loads(body.strip())
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    candidates = []
    if isinstance(error, dict):
        candidates += [error.get("message"), error.get("msg"), error.get("code")]
    elif isinstance(error, str):
        candidates.append(error)
    candidates += [payload.get("message"), payload.get("msg"), payload.get("Message"), payload.get("code")]
    return next((str(one).strip() for one in candidates if isinstance(one, (str, int)) and str(one).strip()), "")


def _clip(text: str) -> str:
    collapsed = " ".join(text.split()).strip(" ;:,\uff1a\uff1b\uff0c")
    if len(collapsed) <= SUMMARY_DETAIL_CHARS:
        return collapsed
    return collapsed[: SUMMARY_DETAIL_CHARS - 1].rstrip() + "…"


__all__ = ["SUMMARY_DETAIL_CHARS", "short_detail", "status_of", "summarize"]
