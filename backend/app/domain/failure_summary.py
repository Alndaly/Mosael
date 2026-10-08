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
- 没有 key 的(第三方原话)同样只做这一步清理;
- 插件说了一句人话的(参数里的 `summary`,ComfyUI:「ComfyUI 执行到「KSampler」这一步出错」)就是它;插件生成失败没说的,只留原因本身
  —— 「「连接名」生成失败:」那截前缀在失败卡的标题和脚注里已经说过了。

旁边两样:`detail_of`(原文,收进「详情」;和那一句说的是同一件事、没有多出信息时不给)、`hint_of`(认得出的原因和怎么修:
一句原因、几步修法,要敲的命令单独一格 —— 失败卡把命令摆成等宽的一块、带复制;画板格子读 `hint_text` 拼好的一段)。

不翻、不猜上游的原话,只是不把它整段搬到用户眼前。
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.ai.providers.contracts.failures import UPSTREAM_ERROR_KEYS, http_status_category
from app.core.i18n import is_message_key, read_param, t

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


#: 只是「谁失败了:原因」这一层壳的那几个 key:一句人话里只留原因(谁失败了在失败卡的标题和脚注里)。
_WRAPPER_KEYS = frozenset({"providerErr_pluginFailed"})


def summarize(error: str | None, key: str, params: dict[str, Any] | None, locale: str) -> str:
    """一次失败给人看的那一句话(按 `locale` 翻)。`error` 是原文,`key` / `params` 是它的文案 key 与参数(没有就是空)。"""
    fields = dict(params or {})
    said = read_param(fields.get("summary"), locale) if fields.get("summary") else ""
    if isinstance(said, str) and said.strip():
        return _clip(said)
    if key in _WRAPPER_KEYS and isinstance(fields.get("detail"), str) and fields["detail"].strip():
        return short_detail(fields["detail"])
    if key and is_message_key(key):
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


def detail_of(error: str | None, key: str, params: dict[str, Any] | None, locale: str) -> str | None:
    """原文(失败卡、画板格子的「详情」里给):插件给的原话(参数里的 `original`,ComfyUI 的「KSampler: …」)、上游的原话(`detail`),
    都没有就是记下的那句失败原因。它和那一句人话说的是同一件事、没有多出任何信息时是 None —— 不摆一个点开还是那句话的「详情」。"""
    fields = dict(params or {})
    raw = next((fields[key] for key in ("original", "detail") if isinstance(fields.get(key), str) and fields[key].strip()),
               error)
    text = str(raw or "").strip()
    if not text:
        return None
    summary = summarize(error, key, params, locale)
    if _same(text, summary):
        return None
    return text


def hint_of(params: dict[str, Any] | None, locale: str) -> dict[str, Any] | None:
    """认得出的原因和怎么修(插件说的 `hint`,见 plugins.runtime.failure_shape),按 `locale` 读成字:
    `{"cause": 一句或 None, "steps": [{"text": 一句, "command": 原样的命令或 None}]}`。没有就是 None。"""
    hint = (params or {}).get("hint")
    if not isinstance(hint, dict):
        return None
    cause = _said(hint.get("cause"), locale)
    steps = []
    for step in hint.get("steps") if isinstance(hint.get("steps"), list) else []:
        if not isinstance(step, dict):
            continue
        text = _said(step.get("text"), locale)
        command = step.get("command").strip() if isinstance(step.get("command"), str) and step["command"].strip() else None
        if text or command:
            steps.append({"text": text or "", "command": command})
    if not cause and not steps:
        return None
    return {"cause": cause, "steps": steps}


def hint_text(params: dict[str, Any] | None, locale: str) -> str:
    """同一份「原因 + 怎么修」拼成一段字(画板格子「详情」的悬停里只摆得下一段):原因一行,修法一步一行(多步时编号),命令单独一行。"""
    hint = hint_of(params, locale)
    if hint is None:
        return ""
    lines = [hint["cause"]] if hint["cause"] else []
    numbered = len(hint["steps"]) > 1
    for index, step in enumerate(hint["steps"], start=1):
        if step["text"]:
            lines.append(f"{index}. {step['text']}" if numbered else step["text"])
        if step["command"]:
            lines.append(step["command"])
    return "\n".join(lines)


def _said(value: Any, locale: str) -> str | None:
    """一句存着没翻的话(按语言分的 `authored_text`,或一个字符串)按这个语言读成字;空的是 None。"""
    said = read_param(value, locale) if value else ""
    return said.strip() if isinstance(said, str) and said.strip() else None


#: 比「是不是同一件事」时不算的句末标点
_TRAILING = re.compile(r"[\s.;:,\u3002\uff1b\uff1a\uff0c]+$")


def _flat(text: str) -> str:
    return _TRAILING.sub("", " ".join(text.split()))


def _same(raw: str, summary: str) -> bool:
    """原文和那一句说的是不是同一件事:去掉空白和句末标点之后一样。

    那一句是原文去掉套话、地址、截到一句的样子时**不算**一样 —— 去掉的正是原文多出来的那些(地址、回包、状态码),发布、定时运行
    这类只有原文的失败,「详情」里要看得到它们。"""
    return _flat(raw) == _flat(summary)


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


__all__ = ["SUMMARY_DETAIL_CHARS", "detail_of", "hint_of", "hint_text", "short_detail", "status_of", "summarize"]
