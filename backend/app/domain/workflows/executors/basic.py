"""纯计算类节点:不碰领域数据,只做控制流与文本/JSON 处理。"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.db.models import Workflow
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.executors import register

HTTP_NODE_TIMEOUT_SECONDS = 60
HTTP_TEXT_CAP = 100_000
CODE_TIMEOUT_SECONDS = 20
CODE_OUTPUT_CAP = 256 * 1024
DELAY_MAX_SECONDS = 300

# 与插件运行时同一信任级别:本地用户自己写的代码,进程隔离 + 超时 + 输出上限。
_CODE_WRAPPER = """\
import json, sys
payload = json.load(sys.stdin)
scope = {"inputs": payload.get("inputs") or {}}
exec(payload["code"], scope)
print(json.dumps({"output": scope.get("output")}, ensure_ascii=False, default=str))
"""


@register("start")
def start(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    # 引擎对 start 有特殊处理(合并运行参数);注册表仍登记它,保证「每种节点都有执行器」
    # 的不变量成立(子图校验/覆盖测试都依赖这一点)。
    return dict(config.get("params") or {})


@register("condition")
def condition(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    left = config.get("left")
    right = config.get("right")
    op = str(config.get("op", "equals"))
    left_text = "" if left is None else str(left)
    right_text = "" if right is None else str(right)

    def as_number(value: Any) -> float | None:
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return None

    if op == "equals":
        result = left_text == right_text
    elif op == "not_equals":
        result = left_text != right_text
    elif op == "contains":
        result = right_text in left_text
    elif op == "not_contains":
        result = right_text not in left_text
    elif op == "empty":
        result = not left_text.strip()
    elif op == "not_empty":
        result = bool(left_text.strip())
    elif op in ("gt", "lt"):
        left_num, right_num = as_number(left), as_number(right)
        if left_num is None or right_num is None:
            raise WorkflowDomainError(f"条件 {op} 需要数值,得到: {left_text!r} / {right_text!r}")
        result = left_num > right_num if op == "gt" else left_num < right_num
    else:
        raise WorkflowDomainError(f"未知条件运算符: {op}")
    return {"result": result}


@register("http_request")
def http_request(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    method = str(config.get("method") or "GET").upper()
    url = str(config.get("url", ""))
    headers = {str(k): str(v) for k, v in dict(config.get("headers") or {}).items()}
    body = config.get("body")
    content = None if body in (None, "") or method == "GET" else str(body).encode()
    response = httpx.request(method, url, headers=headers, content=content, timeout=HTTP_NODE_TIMEOUT_SECONDS)
    text = response.text[:HTTP_TEXT_CAP]
    try:
        parsed: Any = response.json()
    except ValueError:
        parsed = None
    return {"status": response.status_code, "text": text, "json": parsed}


@register("code")
def code(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    import subprocess
    import sys

    payload = json.dumps({"code": str(config.get("code", "")), "inputs": dict(config.get("input") or {})})
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-c", _CODE_WRAPPER],
            input=payload.encode(),
            capture_output=True,
            timeout=CODE_TIMEOUT_SECONDS,
            env={"PATH": "/usr/bin:/bin"},
        )
    except subprocess.TimeoutExpired as exc:
        raise WorkflowDomainError(f"代码节点超时({CODE_TIMEOUT_SECONDS}s)") from exc
    if completed.returncode != 0:
        raise WorkflowDomainError(f"代码节点出错: {completed.stderr.decode(errors='replace')[:500]}")
    stdout = completed.stdout[:CODE_OUTPUT_CAP]
    try:
        return {"output": json.loads(stdout.decode())["output"]}
    except (ValueError, KeyError) as exc:
        raise WorkflowDomainError("代码节点输出无法解析(请把结果赋给 output 变量)") from exc


@register("template")
def template(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    # interpolate 已在 config 解析阶段完成,这里只需转成文本。
    return {"text": str(config.get("template", ""))}


@register("json_extract")
def json_extract(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
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
def text_transform(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    text = str(config.get("text", ""))
    op = str(config.get("op", "trim"))
    find = str(config.get("find", ""))
    if op == "trim":
        out = text.strip()
    elif op == "upper":
        out = text.upper()
    elif op == "lower":
        out = text.lower()
    elif op == "replace":
        out = text.replace(find, str(config.get("replace", "")))
    elif op == "regex_extract":
        match = re.search(find, text) if find else None
        out = "" if match is None else (match.group(1) if match.groups() else match.group(0))
    elif op == "length":
        out = str(len(text))
    else:
        raise WorkflowDomainError(f"未知文本处理方式: {op}")
    return {"text": out, "length": len(out)}


@register("delay")
def delay(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    try:
        seconds = float(config.get("seconds") if config.get("seconds") not in (None, "") else 1)
    except (TypeError, ValueError):
        seconds = 1.0
    seconds = max(0.0, min(DELAY_MAX_SECONDS, seconds))
    time.sleep(seconds)
    return {"waited": seconds}
