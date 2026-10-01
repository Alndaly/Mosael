"""代码字段里的 `{{…}}` 改成读入参 —— 改写后的代码和插值时代**说的是同一件事**。

代码字段(「执行脚本」的 expression、「代码」节点的 code)不再插值(见 graph_rules.code_fields):上游的值
走节点的入参(`input`),作为数据交进代码。老图里写在代码里的引用要改成读入参,而改写的规矩只有一条 ——
**引用落在哪,就按那里原来的意思读**:

- 代码处(`{{n.count}} * 2`)→ `input.k`(JS)/ `inputs["k"]`(Python):原来是把上游的文字当代码拼进去,
  现在是上游的值本身 —— 数字、布尔一样,一段文字就不再被当成代码执行。
- 字符串里(`"前{{n.t}}后"`)→ 断开字符串,拼上**和插值同一种写法的文字**:插值把值写成文字走的是
  graph_rules.as_text —— 对象 / 列表 / 布尔写成 JSON、`None` 写成空串。改写成 `str(…)` / `String(…)` 的话,
  `json.loads('{{llm.obj}}')` 拿到的是 Python 的 repr(当场崩)、`'{{c.result}}' == 'true'` 永远是假。
  所以拼的是 `as_text` 的等价表达式(`PY_AS_TEXT` / `JS_AS_TEXT`)。
- JS 模板字符串的文字里 → `${as_text(input.k)}`;模板字符串的 `${…}` 里是代码,按代码处改。
- 注释里照代码处写。

这是一个只认字符串、注释、JS 模板字符串(连同 `${…}` 嵌套)的小扫描器:正则字面量、f-string 花括号里
再套引号这类写法认不出,那几处按代码处改,结果仍是一段合法、不执行上游文字的代码。

迁移(db.migrations)和「图升级」(graph_upgrade:导入旧文件、恢复旧修订)用的都是这一份。
"""

from __future__ import annotations

import re
from collections.abc import Callable

#: 代码里的引用。和 graph_rules.VARIABLE_RE 同一个写法。
REFERENCE = re.compile(r"\{\{\s*([\w.-]+)\s*\}\}")

#: graph_rules.as_text 的 Python 等价表达式:字符串原样、None 是空串、布尔 / 对象 / 列表写成 JSON、其余 str()。
#: 写成一个就地调用的 lambda,而不是在代码开头加一个函数:开头加东西会挤掉 `from __future__` 必须是第一句的位置。
PY_AS_TEXT = (
    '(lambda v: v if isinstance(v, str) else "" if v is None else '
    '__import__("json").dumps(v, ensure_ascii=False, default=str) '
    "if isinstance(v, (bool, dict, list, tuple)) else str(v))"
)
#: 同一件事的 JS 写法(「执行脚本」是一个表达式,也加不了语句)。
JS_AS_TEXT = "(v=>typeof v==='string'?v:v==null?'':JSON.stringify(v))"

#: 扫描时所在的位置:代码(含注释)、字符串、JS 模板字符串的文字部分。
CODE, STRING, TEMPLATE = "code", "str", "tpl"

#: 一个改写点:看 `code[i:]` 开头,在 `where` 这种位置上要不要换,换成什么、吃掉到哪。
#: `quotes` 是当前字符串的(开头含前缀, 结尾),只在 STRING 里有。
Hook = Callable[[str, int, str, tuple[str, str]], "tuple[str, int] | None"]


def _read(language: str, key: str) -> str:
    return f"input.{key}" if language == "js" else f'inputs["{key}"]'


def _as_text(language: str, key: str) -> str:
    return f"{JS_AS_TEXT if language == 'js' else PY_AS_TEXT}({_read(language, key)})"


def references_become_input(code: str, language: str, key_of: Callable[[str], str]) -> str:
    """把代码里的 `{{a.b}}` 改成读入参,按落的位置保持原来的意思(见模块说明)。`key_of(路径)` 给入参的键。"""

    def hook(text: str, i: int, where: str, quotes: tuple[str, str]) -> tuple[str, int] | None:
        found = REFERENCE.match(text, i)
        if found is None:
            return None
        key = key_of(found.group(1))
        if where == STRING:
            return f"{quotes[1]} + {_as_text(language, key)} + {quotes[0]}", found.end()
        if where == TEMPLATE:
            return "${" + _as_text(language, key) + "}", found.end()
        return _read(language, key), found.end()

    return scan(code, language, hook)


#: 1.8.1 那版改写在字符串里留下的读法:`"前" + String(input.k) + "后"` / `"前" + str(inputs["k"]) + "后"`。
_JS_STRING_READ = re.compile(r"""(?<=['"] \+ )String\(input\.(\w+)\)(?= \+ ['"])""")
_PY_STRING_READ = re.compile(r"""(?<=['"] \+ )str\(inputs\["(\w+)"\]\)(?= \+ [rRbBuUfF]{0,2}['"])""")
#: 同一版在 JS 模板字符串里留下的 `${input.k}`(它把整个模板字符串当文字,`${…}` 里的也一样写)。
_JS_TEMPLATE_READ = re.compile(r"\$\{input\.(\w+)\}")


def string_reads_keep_their_text(code: str, language: str, keys: set[str]) -> str:
    """1.8.1 改写出的那几种**精确形态**换成和插值同义的写法;只认 `keys` 里的入参(那次改写起的键)。

    - 字符串断开处的 `String(input.k)` / `str(inputs["k"])` → as_text 的等价表达式;
    - 模板字符串文字里的 `${input.k}` → `${as_text(input.k)}`;
    - 模板字符串 `${…}` 代码里的 `${input.k}`(那一版把 `${ {{a.n}} * 2 }` 改成了 `${ ${input.a_n} * 2 }`,
      语法错误)→ `input.k`。

    改过的不再是这几种形态,所以重跑什么都不做。
    """

    def hook(text: str, i: int, where: str, _quotes: tuple[str, str]) -> tuple[str, int] | None:
        if language == "js":
            found = _JS_TEMPLATE_READ.match(text, i)
            if found is not None and found.group(1) in keys:
                if where == TEMPLATE:
                    return "${" + _as_text(language, found.group(1)) + "}", found.end()
                if where == CODE:
                    return _read(language, found.group(1)), found.end()
        if where != CODE:
            return None
        found = (_JS_STRING_READ if language == "js" else _PY_STRING_READ).match(text, i)
        if found is not None and found.group(1) in keys:
            return _as_text(language, found.group(1)), found.end()
        return None

    return scan(code, language, hook)


def scan(code: str, language: str, hook: Hook) -> str:
    """逐字走一遍代码,记着自己在代码、字符串、模板字符串(及其 `${…}`)、注释里的哪一处,每一处先问 `hook`。"""
    out: list[str] = []
    i = 0
    #: 位置栈:("code",) 顶层代码;("expr", 花括号深度) 模板字符串里的 `${…}`;("str", 开头含前缀, 结尾);
    #: ("tpl",) 模板字符串的文字;("line",) / ("block",) 注释。
    stack: list[tuple] = [("code",)]
    while i < len(code):
        frame = stack[-1]
        kind = frame[0]
        where = STRING if kind == "str" else TEMPLATE if kind == "tpl" else CODE
        hit = hook(code, i, where, (frame[1], frame[2]) if kind == "str" else ("", ""))
        if hit is not None:
            out.append(hit[0])
            i = hit[1]
            continue
        ch = code[i]
        if kind in ("code", "expr"):
            if language == "js" and code.startswith("//", i):
                stack.append(("line",))
            elif language == "js" and code.startswith("/*", i):
                stack.append(("block",))
            elif language == "python" and ch == "#":
                stack.append(("line",))
            elif language == "js" and ch == "`":
                stack.append(("tpl",))
            elif ch in "'\"":
                quote = code[i:i + 3] if language == "python" and code.startswith(ch * 3, i) else ch
                #: Python 字符串的前缀(f / r / b / rb …)已经作为代码写出去了;断开之后接上的那一段要带同样的前缀
                start = i
                while language == "python" and start > 0 and i - start < 2 and code[start - 1] in "rRbBuUfF":
                    start -= 1
                prefix = code[start:i] if start == 0 or not (code[start - 1].isalnum() or code[start - 1] == "_") else ""
                stack.append(("str", prefix + quote, quote))
                out.append(quote)
                i += len(quote)
                continue
            elif kind == "expr" and ch == "{":
                stack[-1] = ("expr", frame[1] + 1)
            elif kind == "expr" and ch == "}":
                if frame[1] == 0:
                    stack.pop()
                else:
                    stack[-1] = ("expr", frame[1] - 1)
        elif kind == "line":
            if ch == "\n":
                stack.pop()
        elif kind == "block":
            if code.startswith("*/", i):
                out.append("*/")
                i += 2
                stack.pop()
                continue
        else:  # 字符串 / 模板字符串的文字
            if ch == "\\" and i + 1 < len(code):
                out.append(code[i:i + 2])
                i += 2
                continue
            if kind == "tpl" and code.startswith("${", i):
                out.append("${")
                i += 2
                stack.append(("expr", 0))
                continue
            closing = frame[2] if kind == "str" else "`"
            if code.startswith(closing, i):
                out.append(closing)
                i += len(closing)
                stack.pop()
                continue
        out.append(ch)
        i += 1
    return "".join(out)
