"""纯计算类节点:不碰领域数据,只做控制流与文本/JSON 处理。"""

from __future__ import annotations

import json
import math
import re
import time
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.domain.workflows import WorkflowDomainError, as_text
from app.domain.workflows.executors.registry import RunScope, register
from app.domain.workflows.executors.common import wait_until

HTTP_NODE_TIMEOUT_SECONDS = 60
HTTP_TEXT_CAP = 100_000
CODE_TIMEOUT_SECONDS = 20
DELAY_MAX_SECONDS = 300


@register("start")
def start(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    # 引擎对 start 有特殊处理(合并运行参数);注册表仍登记它,保证「每种节点都有执行器」
    # 的不变量成立(子图校验/覆盖测试都依赖这一点)。
    return dict(config.get("params") or {})


def _is_empty(value: Any) -> bool:
    """「空」按值的样子判:没有值、空列表、空对象、只有空白的文字。

    此前先 `as_text` 再判 —— 而 as_text 把 `[]` / `{}` 写成 JSON 的 `"[]"` / `"{}"`,两个字符,
    不空:「查询结果为空就走另一支」永远走不到,正好判反。
    """
    if value is None:
        return True
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    if isinstance(value, str):
        return not value.strip()
    return False


def _as_number(value: Any) -> float | None:
    """当数用时是几;不是有限的数就是 None。布尔不算数(`true` 和 `1` 不是一回事)。"""
    if isinstance(value, bool):
        return None
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


@register("condition")
def condition(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    left = config.get("left")
    right = config.get("right")
    op = str(config.get("op", "equals"))
    left_text = as_text(left)
    right_text = as_text(right)

    def same() -> bool:
        # 两边都是数就按数比:上游算出来的 30.0 和手填的 30 是同一个数,按文字比永远不等。
        left_num, right_num = _as_number(left), _as_number(right)
        if left_num is not None and right_num is not None:
            return left_num == right_num
        return left_text == right_text

    if op == "equals":
        result = same()
    elif op == "not_equals":
        result = not same()
    elif op == "contains":
        result = right_text in left_text
    elif op == "not_contains":
        result = right_text not in left_text
    elif op == "empty":
        result = _is_empty(left)
    elif op == "not_empty":
        result = not _is_empty(left)
    elif op in ("gt", "lt"):
        left_num, right_num = _as_number(left), _as_number(right)
        if left_num is None or right_num is None:
            raise WorkflowDomainError("wfErr_conditionNeedsNumbers", params={"op": op, "left": left_text, "right": right_text})
        result = left_num > right_num if op == "gt" else left_num < right_num
    else:
        raise WorkflowDomainError("wfErr_unknownConditionOp", params={"op": op})
    return {"result": result}


def run_http(*, method: str, url: str, headers: dict[str, str], body: str) -> dict[str, Any]:
    """一次外部 HTTP 调用。**工作流节点与智能体工具共用这一个实现** —— 同一个能力在两个界面
    上应当是同一段代码,否则超时、截断上限这些约定迟早在一边被改、另一边不知道。"""
    verb = (method or "GET").upper()
    content = None if not body or verb == "GET" else body.encode()
    response = httpx.request(verb, url, headers=headers, content=content, timeout=HTTP_NODE_TIMEOUT_SECONDS)
    try:
        parsed: Any = response.json()
    except ValueError:
        parsed = None
    return {"status": response.status_code, "text": response.text[:HTTP_TEXT_CAP], "json": parsed}


@register("http_request")
def http_request(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    return run_http(
        method=str(config.get("method") or "GET"),
        url=str(config.get("url", "")),
        headers={str(k): str(v) for k, v in dict(config.get("headers") or {}).items()},
        body=as_text(config.get("body")),
    )


def run_python(code_text: str, inputs: dict[str, Any]) -> dict[str, Any]:
    """跑一段用户代码,返回 `{"output": ...}`。**工作流节点与智能体工具共用这一个实现**。

    隔离在 `domain/sandbox` 里(内核强制的沙箱 / 独立容器);这里只做领域错误的转换。此前这个
    函数自己"隔离":子进程 + `-I` + 最小 env —— 而那拦不住读库、写盘、连本机服务(见
    tests/test_sandbox.py 开头跑出来的那几行)。
    """
    from app.domain import sandbox

    try:
        return sandbox.run_code(code_text, inputs, timeout=CODE_TIMEOUT_SECONDS)
    except sandbox.SandboxUnavailable as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    except sandbox.SandboxError as exc:
        raise WorkflowDomainError.from_error(exc) from exc


@register("code")
def code(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    return run_python(str(config.get("code", "")), dict(config.get("input") or {}))


@register("template")
def template(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    # interpolate 已在 config 解析阶段完成,这里只需转成文本。
    return {"text": as_text(config.get("template"))}


@register("json_extract")
def json_extract(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """Walk a JSON string/object by a dot path (list indices as integers). Missing → None."""
    source = config.get("source")
    data: Any = source
    if isinstance(source, str):
        try:
            data = json.loads(source)
        except ValueError:
            data = source  # not JSON — treat the raw string as the value
    value: Any = data
    for part in [p for p in str(config.get("path", "")).split(".") if p]:
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list):
            try:
                value = value[int(part)]
            except (ValueError, IndexError):
                value = None
        else:
            value = None
        if value is None:
            break
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False)
    return {"value": value, "text": text}


@register("text_transform")
def text_transform(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """`length` 输出是**这一步处理的那段文字**有多长。

    此前一律取结果串的长度:op=length 时结果是 "12" 这串数字,length 就成了 2。其余几种处理,
    结果串就是那段文字,取它的长度。
    """
    text = as_text(config.get("text"))
    op = str(config.get("op", "trim"))
    find = as_text(config.get("find"))
    # 查找串为空:replace 会在**每个字符之间**插一遍替换串("ab" → "XaXbX"),正则则永远匹配空串 ——
    # 两种都不是任何人想要的结果。声明里标了必填(active_when),这里兜住引用落空成空串的那种。
    if op in ("replace", "regex_extract") and not find:
        raise WorkflowDomainError("wfErr_textFindEmpty")
    if op == "trim":
        out = text.strip()
    elif op == "upper":
        out = text.upper()
    elif op == "lower":
        out = text.lower()
    elif op == "replace":
        out = text.replace(find, as_text(config.get("replace")))
    elif op == "regex_extract":
        try:
            match = re.search(find, text)
        except re.error as exc:
            # re 的报错是英文原话(`missing ), unterminated subpattern`),只说出是哪个正则、错在第几个字符。
            raise WorkflowDomainError(
                "wfErr_textRegexInvalid", params={"pattern": find, "position": (exc.pos or 0) + 1}
            ) from exc
        out = "" if match is None else (match.group(1) if match.groups() else match.group(0))
    elif op == "length":
        return {"text": str(len(text)), "length": len(text)}
    else:
        raise WorkflowDomainError("wfErr_unknownTextOp", params={"op": op})
    return {"text": out, "length": len(out)}


@register("delay")
def delay(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    try:
        seconds = float(config.get("seconds") if config.get("seconds") not in (None, "") else 1)
    except (TypeError, ValueError):
        seconds = 1.0
    seconds = max(0.0, min(DELAY_MAX_SECONDS, seconds))
    # 和等子任务是同一种等(见 common.wait_until):不占连接,这一轮在停(取消、别的节点失败)
    # 就不再等。此前是一句 time.sleep —— 取消一条正在延时的工作流要等满那几分钟。
    deadline = time.monotonic() + seconds
    wait_until(lambda _db: time.monotonic() >= deadline or None, release=db, deadline=deadline)
    return {"waited": seconds}
