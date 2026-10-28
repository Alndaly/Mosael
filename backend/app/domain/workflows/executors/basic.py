"""纯计算类节点:不碰领域数据,只做控制流与文本/JSON 处理。"""

from __future__ import annotations

import json
import math
import re
import time
from typing import Any

from sqlalchemy.orm import Session

from app.core import outbound_guard
from app.domain.workflows.errors import WorkflowDomainError
from app.domain.workflows.graph_rules import as_text
from app.domain.workflows.executors.registry import RunScope, register
from app.domain.workflows.executors.numbers import at_least, whole_number
from app.domain.workflows.executors.common import truthy, wait_until

HTTP_NODE_TIMEOUT_SECONDS = 60
HTTP_TEXT_CAP = 100_000
#: 一次 HTTP 节点 / 智能体 HTTP 工具最多收多少字节。交给下游的文本截在 HTTP_TEXT_CAP,而此前截在**整份读进内存之后** ——
#: 地址是用户 / 模板 / 模型写的,碰上一个几个 GB 的文件就整份进内存(SEC-4)。接口回的 JSON 远小于这个数。
HTTP_MAX_BYTES = 16 * 1024 * 1024
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
    上应当是同一段代码,否则超时、截断上限这些约定迟早在一边被改、另一边不知道。

    请求体是一段 JSON、调用方又没说 Content-Type 时,带上 `application/json`:此前不带,
    多数 API 把它当表单或纯文本,回一个看不出原因的 400/415。
    """
    verb = (method or "GET").upper()
    content = None if not body or verb == "GET" else body.encode()
    if content is not None and not any(key.lower() == "content-type" for key in headers) and _is_json(body):
        headers = {**headers, "Content-Type": "application/json"}
    #: 地址是用户 / 模板 / 模型写的:经内网守卫出去(只许公网或部署允许名单里的地址,连的是查过的那个 IP)。
    #: 不跟随重定向,和此前一样 —— 3xx 原样交回(按非 2xx 算失败,或由 fail_on_error 关掉)。
    response = outbound_guard.send(
        verb, url, headers=headers, content=content, timeout=HTTP_NODE_TIMEOUT_SECONDS, max_bytes=HTTP_MAX_BYTES
    ).response
    try:
        parsed: Any = response.json()
    except ValueError:
        parsed = None
    return {"status": response.status_code, "text": response.text[:HTTP_TEXT_CAP], "json": parsed}


def _is_json(text: str) -> bool:
    stripped = text.strip()
    if not stripped.startswith(("{", "[")):
        return False
    try:
        json.loads(stripped)
    except ValueError:
        return False
    return True


@register("http_request")
def http_request(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """**非 2xx 算失败**(高级选项 fail_on_error 可以关掉)。

    此前 404、500 都是"成功":下游拿着一段错误页当数据往下跑,失败出现在隔了几个节点、看不出
    原因的地方。要自己按状态码分支的,把 fail_on_error 设成 no,读 `status`。
    """
    try:
        result = run_http(
            method=str(config.get("method") or "GET"),
            url=str(config.get("url", "")),
            headers={str(k): str(v) for k, v in dict(config.get("headers") or {}).items()},
            body=as_text(config.get("body")),
        )
    except (outbound_guard.OutboundBlocked, outbound_guard.ResponseTooLarge) as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    fail_on_error = str(config.get("fail_on_error") or "").strip()
    if not 200 <= result["status"] < 300 and (truthy(fail_on_error) if fail_on_error else True):
        raise WorkflowDomainError(
            "wfErr_httpStatus",
            params={"status": result["status"], "reason": result["text"][:200]},
            details={"status": result["status"], "text": result["text"][:2000]},
        )
    return {"status": result["status"], "text": result["text"], "json": result["json"]}


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


@register("list_chunk")
def list_chunk(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """把一串拆成等长的几批:分批分析、分批拉取的公共积木(评论区全量分析就是它)。

    批与批不重叠、顺序不变;空串/空列表 = 零批。给的不是一串就明说,不悄悄当成一批。
    """
    raw = config.get("items")
    items: Any = raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            items = []
        else:
            try:
                items = json.loads(text)
            except ValueError as exc:
                raise WorkflowDomainError("wfErr_listChunkNotAList", params={"kind": "text"}) from exc
    if items is None:
        items = []
    if not isinstance(items, list):
        raise WorkflowDomainError("wfErr_listChunkNotAList", params={"kind": type(items).__name__})
    #: 不写 `or 100`:那会把「填了 0」悄悄变成默认(loop_while 的注释里挂着这个反模式)。
    #: 缺省走默认,填了 0 由 at_least 当场报错。
    size = whole_number(config, "size", node_type="list_chunk", default=100)
    size = min(at_least(size, 1, key="size", node_type="list_chunk"), 500)
    batches = [items[i : i + size] for i in range(0, len(items), size)]
    return {"batches": batches, "count": len(batches), "total": len(items)}


def _fenced_json(text: str, *, default: Any) -> Any:
    """模型的 text 输出常裹着 ```json 围栏 —— 和「LLM 生成」自己的 json 输出同一种解析(executors.ai)。

    只认**围栏**这一种:散文里夹着的 `{…}` 片段不去捞,那种文字照旧当一个值(见 json_extract 的说明)。
    """
    if not text.strip().startswith("```"):
        return default
    from app.domain.workflows.executors.ai import _parse_json_response

    try:
        return _parse_json_response(text)
    except ValueError:
        return default


@register("json_extract")
def json_extract(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """按路径从 JSON(一段 JSON 文本,或上游交回的对象 / 列表)里取一个值。路径写法见 parse_json_path。

    **取不到就报错,说清在哪一段断的、那一层有什么。** 此前取不到静默交出 null:下游拿着空值往下跑,失败出现在隔了几个
    节点、看不出原因的地方;`a.b[0].c` 这种最常见的写法也不认(`[0]` 被当成键名「b[0]」),于是「取不到值」。
    `*` 收的是「每一项里有的那几个」,没有的不占位(见 _walk),不算取不到。
    """
    source = config.get("source")
    path = str(config.get("path") or "").strip()
    data: Any = source
    if isinstance(source, str):
        try:
            data = json.loads(source)
        except ValueError:
            data = _fenced_json(source, default=source)  # 不是 JSON:整段文字就是那个值(路径为空时原样交出)
    steps = parse_json_path(path)
    #: 来源是空的:wildcard 开头对空来源是**故意的**宽容 ——「每一个」就是零个,_walk 返回 [](basic.py 那头
    #: 有注释)。所以只在**非 wildcard 开头**且要往里走时才拦:那种情况旧代码会报一句把人绕懵的
    #: 「走到「0」这一段…那一层是:""」(维护者填了数组数据却报「不能为空」,照着改永远修不好)。
    if steps and steps[0] != WILDCARD and (data is None or data == ""):
        raise WorkflowDomainError("wfErr_jsonSourceEmpty", params={"path": path})
    value = _walk(data, steps, path=path)
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False)
    return {"value": value, "text": text}


#: 路径里的「这一串里的每一个」。
WILDCARD = "*"
#: 路径里的保留段「这一层的长度」:列表/字典/字符串给 len,其余走不通(取不到长度)。不是键名 —— 列表长度这种
#: 小操作不用为此开一个 code 节点(Docker 沙箱);`$length` 开头带 $,真实 JSON 键几乎不会撞。
LENGTH = "$length"
_PATH_STEP = re.compile(
    r"""\.?(?:
        \[\s*(?P<index>-?\d+)\s*\]            # [0]、[-1]
      | \[\s*(?P<star>\*)\s*\]                # [*]
      | \[\s*"(?P<dq>(?:[^"\\]|\\.)*)"\s*\]   # ["带 . 的键"]
      | \[\s*'(?P<sq>(?:[^'\\]|\\.)*)'\s*\]   # ['带 . 的键']
      | (?P<key>[^.\[\]]+)                    # 键名、数字下标(items.0)、*
    )""",
    re.VERBOSE,
)


def parse_json_path(path: str) -> list[str | int]:
    """把路径拆成一步一步:键名是 str,方括号里的下标是 int,`*` / `[*]` 是 WILDCARD。

    认的写法:`data.items.0.title`、`data.items[0].title`、`[0].name`、`items[-1]`、`results.*.asset_id`、`results[*].id`、
    `meta["a.b"]`、`$length`(整个值的长度)/ `items.$length`(某一层的长度);开头的 `$` / `$.`(JSONPath 的根)可写可不写。
    空路径 = 整个值。写坏了(方括号没闭合)就报错,不猜。
    """
    text = path.strip()
    #: JSONPath 的根 `$` 可写可不写 —— 但只认 `$` / `$.` / `$[`,不把 `$length`(长度保留段)的根符号剥掉。
    if text == "$" or text.startswith("$.") or text.startswith("$["):
        text = text[1:]
    steps: list[str | int] = []
    position = 0
    while position < len(text):
        match = _PATH_STEP.match(text, position)
        if not match or match.end() == position:
            raise WorkflowDomainError("wfErr_jsonPathInvalid", params={"path": path, "at": text[position:][:40]})
        if match.group("index") is not None:
            steps.append(int(match.group("index")))
        elif match.group("star") is not None:
            steps.append(WILDCARD)
        elif match.group("dq") is not None or match.group("sq") is not None:
            quoted = match.group("dq") if match.group("dq") is not None else match.group("sq")
            steps.append(re.sub(r"\\(.)", r"\1", quoted))
        else:
            steps.append(match.group("key").strip())
        position = match.end()
    return [step for step in steps if step != ""]


def _step_text(steps: list[str | int]) -> str:
    """走过的那几步写回路径的样子(报错里说「在哪一段断的」)。"""
    out = ""
    for step in steps:
        out += f"[{step}]" if isinstance(step, int) else (f".{step}" if out else str(step))
    return out


def _available(value: Any) -> str:
    """断的那一层长什么样 —— 报错里给人看,好知道该写哪个:对象写成 `{键, 键}`,列表写成 `[0..n]`,其余是那个值本身(截短)。"""
    if isinstance(value, dict):
        keys = [str(key) for key in value]
        return "{" + ", ".join(keys[:20]) + (", …" if len(keys) > 20 else "") + "}"
    if isinstance(value, list):
        return f"[0..{len(value) - 1}]" if value else "[]"
    shown = json.dumps(value, ensure_ascii=False)
    return shown if len(shown) <= 60 else shown[:60] + "…"


def _walk(value: Any, steps: list[str | int], *, path: str, done: list[str | int] | None = None) -> Any:
    """按拆好的路径往下走;哪一步走不下去就报 wfErr_jsonPathMissing(在哪一段、那一层有什么)。

    `*` 是「这一串里的每一个」:余下的路径对每一项各走一遍,走不到的(没有那一格)不占位 —— 从循环交出的一串结果里取出每一项的
    某一格(模特上身图的 `*.on_model_clip.asset_id`)。
    """
    done = list(done or [])
    for index, step in enumerate(steps):
        if step == WILDCARD:
            #: 空的(上游什么都没交)当空的一串:「每一个」就是一个都没有。别的单个值不是一串,报错。
            items = [] if value in (None, "") else value if isinstance(value, list) else list(value.values()) if isinstance(value, dict) else None
            if items is None:
                raise _missing(path, done + [step], value)
            picked = []
            for item in items:
                try:
                    picked.append(_walk(item, steps[index + 1:], path=path, done=done + [step]))
                except WorkflowDomainError:
                    continue
            return [one for one in picked if one not in (None, "")]
        found, value = _step(value, step)
        done.append(step)
        if not found:
            raise _missing(path, done, value)
    return value


def _step(value: Any, step: str | int) -> tuple[bool, Any]:
    """走一步:(走到了没有, 走到的值)。没走到时第二格是**这一层**(报错里列它有什么)。

    列表认整数下标(`[0]`,也认 `items.0` 这种写成键名的数字);对象认键名(`[0]` 落在对象上就找键「0」)。
    `$length` 是保留段,不是键名:列表/字典/字符串给 len(其余取值走不通)。
    """
    if step == LENGTH:
        if isinstance(value, (list, dict, str)):
            return True, len(value)
        return False, value
    if isinstance(value, dict):
        key = str(step)
        return (True, value[key]) if key in value else (False, value)
    if isinstance(value, list):
        try:
            position = step if isinstance(step, int) else int(step)
        except ValueError:
            return False, value
        if -len(value) <= position < len(value):
            return True, value[position]
        return False, value
    return False, value


def _missing(path: str, done: list[str | int], level: Any) -> WorkflowDomainError:
    """`done`:走到断的那一步为止(含那一步);`level`:断的那一层。"""
    return WorkflowDomainError(
        "wfErr_jsonPathMissing",
        params={"path": path, "at": _step_text(done), "available": _available(level)},
    )


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
