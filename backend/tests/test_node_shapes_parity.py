"""节点形状契约:跑 contracts/node-shapes.json 的 **Python 一侧**。

`_ANY_NODE`(宿主 + 桥)、`NODE_PATH`(桥)、`_PATH`(插件的 `canvas_edit`)、`_NODE_REF`(工作台智能体)
是**四份各自手写的正则**,说的却是同一件事:「这个字符串是不是一个节点号」。而它们已经分岔过一次 ——
桥那一侧只认顶层节点号,于是维护者那张 18 项的表单里有 6 项在过桥时被拒(`marks.nodes keys must be
top-level node ids`),整条「同步到画布」的链断在那一句话上。

**为什么不共用一份实现**:四处跑在三种语言、两个进程里 —— 后端进程、Electron 主进程、浏览器,以及
一个**沙盒子进程**(插件)。插件那一侧连 `contracts/` 都读不到,所以那边只能带字面量。于是四份正则
必然存在,一致性只能靠**同一份语料 + 各侧的跑手**:这一条是 Python 侧那个跑手,`electron/ipc-contract.test.ts`
和 `frontend/src/features/plugins/workbench/nodeRefs.parity.test.ts` 是另外两个。

**这条测试做三件事**(缺了哪一件都还能让两侧悄悄分岔):

1. **字面量对齐** —— 每一处实现的 `pattern` 必须逐字等于契约那一串。这是「改一处、另一处没改」的
   第一道闸:正则看着还能用,差异只在某个边界上(`{0,16}` vs `{1,16}`、`-?` 在第几段)。
2. **逐条跑用例** —— 不是一个「合法 / 非法」的布尔,而是**每条形状各自点名**哪条收、哪条拒。
   `12` 在 `any_node` 里收、在 `subgraph_path` 里拒,两边都得说得出为什么(见契约的 `divergence`)。
3. **跑真入口** —— 形状对不对最终要由**真的那次调用**说了算。所以下面不只编译正则:插件的
   `canvas_edit` 与后端的 `comfy_locate` 各自被真的喂了一遍契约的用例,并且断言的是它们的**返回值 /
   报错**,不是内部那行正则。

Node 那一侧的三处(桥的 `CANVAS_NODE` / `ANY_NODE` / `NODE_PATH`)从**源码**里读:它们没有导出,
而 `electron/ipc-contract.test.ts` 才是它们的跑手(它走真入口 `parseComfyWorkbenchCall`)。这里读源码
是为了补上验收链的那个洞:`npx vitest run ../electron` **不含 `frontend/src`**,而 `nodeRefs.ts` 那处
断言只在前端 vitest 里时,改坏它就没人拦(实测过)。下面那条前端断言与三条桥的断言因此都留在这一侧。
"""

from __future__ import annotations

import ast
import importlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterator

import pytest

REPO = Path(__file__).resolve().parents[2]
_CONTRACT = REPO / "contracts" / "node-shapes.json"
TOOLS = REPO / "plugins" / "bundled" / "comfyui" / "tools"


def _load() -> dict:
    return json.loads(_CONTRACT.read_text(encoding="utf-8"))


def _shapes() -> list[dict]:
    return _load()["shapes"]


def _shape(name: str) -> dict:
    found = next((one for one in _shapes() if one["name"] == name), None)
    assert found, f"契约里没有形状 {name} —— 它被删了还是改名了?"
    return found


# --- 用例 -----------------------------------------------------------------------------------


def _cases(shape: dict, kind: str) -> list[str]:
    return [str(one) for one in shape["cases"].get(kind) or []]


def _all_cases(shape: dict) -> list[str]:
    return [one for kind in ("ok", "bad") for one in _cases(shape, kind)]


def _oracle(shape: dict) -> re.Pattern[str]:
    """契约那一串自己编出来的正则 —— **锚定**的(实现里那一份带不带 `^…$` 是各自的写法)。"""
    return re.compile(f"^(?:{shape['pattern']})$")


def _unanchored(pattern: str) -> str:
    """去掉首尾的 `^` / `$`。

    **锚是各自的写法,不是判据**:`workflow_library._ANY_NODE` 不带锚(调用点是 `fullmatch`),
    桥的 `ANY_NODE` 带(`.test`),两处说的是同一件事。比之前先把它抹掉 —— 否则「这个判据
    逐字一致」会变成「这个判据的锚也一致」,而锚根本不影响任何一条用例。
    """
    return pattern.removeprefix("^").removesuffix("$")


def test_契约文件在_每条形状都有用例和落点() -> None:
    assert _CONTRACT.is_file(), f"节点形状契约语料缺失: {_CONTRACT}"
    data = _load()
    assert data["contract"] == "node-shapes"
    assert len(data["shapes"]) >= 4, "形状少了 —— 这一节就是全部的一致性保护"
    for shape in data["shapes"]:
        assert shape["cases"].get("ok") and shape["cases"].get("bad"), f"{shape['name']} 没有用例 = 没有保护"
        assert shape["pattern"], f"{shape['name']} 没有 pattern"
    implemented = {impl["shape"] for impl in data["implementations"]}
    assert {shape["name"] for shape in data["shapes"]} <= implemented, "有形状没有任何落点 —— 那它管不住谁"


def test_契约里的用例和它自己的_pattern_对得上() -> None:
    """语料先自洽:实现全对、而契约自己写错了,这条能先抓住(否则四处一起「红得莫名其妙」)。"""
    for shape in _shapes():
        rx = _oracle(shape)
        wrong = [one for one in _cases(shape, "ok") if not rx.fullmatch(one)]
        loose = [one for one in _cases(shape, "bad") if rx.fullmatch(one)]
        assert not wrong, f"{shape['name']}:契约说这些收,它自己的 pattern 却拒:{wrong}"
        assert not loose, f"{shape['name']}:契约说这些拒,它自己的 pattern 却收:{loose}"


# --- 每一处落点的正则:读出来 ------------------------------------------------------------------


def _python_pattern(location: str, symbol: str) -> str:
    """一个 Python 模块里的 `symbol = re.compile("…")` —— 按 AST 读,不 import(插件那些模块要 sys.path)。"""
    tree = ast.parse((REPO / location).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == symbol for t in node.targets):
            continue
        call = node.value
        assert isinstance(call, ast.Call), f"{location} 的 {symbol} 不是一次调用 —— 契约记的落点过期了"
        assert isinstance(call.args[0], ast.Constant), f"{location} 的 {symbol} 的正则不是字面量"
        return str(call.args[0].value)
    raise AssertionError(f"{location} 里找不到 {symbol} —— 契约记的落点过期了")


#: JS 正则 → Python 正则的写法差异。只有这几处,**遇到没见过的写法就红**(而不是悄悄跳过)。
_JS_TO_PY = ((r"(?<", "(?P<"),)


def _js_regex_literal(location: str, symbol: str) -> str:
    """一个 `.cjs` / `.ts` 里的 `const SYMBOL = /…/` —— 读出中间那一截源文本。

    **按字符扫,不按正则猜**:字面量里可以有 `/`(`nodeRefs.NODE_REF` 的字符类 `[\\w&#/[\\]`)、
    可以有 `\\/`,而「第一个斜杠到第二个斜杠」那种写法正好会断在要量的那个边界上。
    扫的时候认三种状态:反斜杠转义、字符类里、普通字符。
    """
    source = (REPO / location).read_text(encoding="utf-8")
    start = re.search(rf"\b{re.escape(symbol)}\s*=\s*/", source)
    assert start, f"{location} 里找不到 {symbol} 的正则字面量 —— 契约记的落点过期了"
    index = start.end()
    out: list[str] = []
    in_class = False
    while index < len(source):
        char = source[index]
        if char == "\\":
            out.append(source[index : index + 2])
            index += 2
            continue
        if char == "[":
            in_class = True
        elif char == "]":
            in_class = False
        elif char == "/" and not in_class:
            return "".join(out)
        elif char == "\n":
            break
        out.append(char)
        index += 1
    raise AssertionError(f"{location} 的 {symbol} 那个正则字面量没有收尾的 `/`")


def _python_view_of_js(pattern: str) -> str:
    for js, py in _JS_TO_PY:
        pattern = pattern.replace(js, py)
    return pattern


def _python_view_of_js(pattern: str) -> str:
    for js, py in _JS_TO_PY:
        pattern = pattern.replace(js, py)
    return pattern


def _implementation_entry(location: str, symbol: str) -> dict:
    for impl in _load()["implementations"]:
        if impl["location"] == location and impl["symbol"] == symbol:
            return impl
    raise AssertionError(f"契约里没有 {location} 的 {symbol} —— 这一处没有落在任何形状上")


@pytest.mark.parametrize(
    "location,symbol",
    [
        ("backend/app/domain/workflow_library.py", "_ANY_NODE"),
        ("backend/app/domain/workbench/agent.py", "_NODE_REF"),
        ("plugins/bundled/comfyui/tools/canvas_edit.py", "_PATH"),
    ],
)
def test_python_那一侧的判据文本逐字等于契约(location: str, symbol: str) -> None:
    """改一处语句、另一处没跟上的第一道闸 —— 这里的差别往往只在某个边界上。"""
    impl = _implementation_entry(location, symbol)
    shape = _shape(impl["shape"])
    assert _unanchored(_python_pattern(location, symbol)) == shape["pattern"], (
        f"{location} 的 {symbol} 和契约的 `{shape['name']}` 不是同一串。\n"
        f"  为什么要紧:{shape['why']}"
    )


@pytest.mark.parametrize(
    "location,symbol",
    [
        ("electron/ipc-contract.cjs", "CANVAS_NODE"),
        ("electron/ipc-contract.cjs", "ANY_NODE"),
        ("electron/ipc-contract.cjs", "NODE_PATH"),
    ],
)
def test_electron_那一侧的判据文本逐字等于契约(location: str, symbol: str) -> None:
    """桥那三处没有导出,所以从源码里读。它们的跑手在 `electron/ipc-contract.test.ts`(走真入口)。"""
    impl = _implementation_entry(location, symbol)
    shape = _shape(impl["shape"])
    assert _unanchored(_js_regex_literal(location, symbol)) == shape["pattern"], (
        f"{location} 的 {symbol} 和契约的 `{shape['name']}` 不是同一串。\n"
        f"  为什么要紧:{shape['why']}"
    )


def test_前端那一处把契约的判据嵌在自己的模式里() -> None:
    """`nodeRefs.NODE_REF` 外面还套了 `#` 前缀和「别把代码块 / 网址 / 连着单词的算进来」那几层。

    所以它不会整条相等 —— 断言的是**契约那一串原样出现在它里面**(`linkNodeRefs` 的真行为由
    `nodeRefs.parity.test.ts` 逐条跑,那一份读的是同一个 `contracts/node-shapes.json`)。

    这一条也**是这道闸在前端那一侧的唯一保险**:验收链跑的是 `npx vitest run ../electron`,不含
    `frontend/src`。把 `NODE_REF` 的 `{0,16}` 改成 `{1,16}`(于是 `#12` 不再变成链接)时,
    `nodeRefs.parity.test.ts` 会红 —— 而它在验收链里**不会被执行**;这里会。
    """
    impl = _implementation_entry("frontend/src/features/plugins/workbench/nodeRefs.ts", "NODE_REF")
    source = (REPO / impl["location"]).read_text(encoding="utf-8")
    assert "contracts/node-shapes.json" in source, (
        "nodeRefs.ts 没有点名它归哪份契约 —— 那正是这条棘轮要防的:两侧各写一份正则而没人知道"
    )
    shape = _shape(impl["shape"])
    literal = _js_regex_literal(impl["location"], impl["symbol"])
    assert shape["pattern"] in literal, (
        f"{impl['location']} 的 NODE_REF 里没有契约 `{shape['name']}` 那一串。\n"
        f"  契约:{shape['pattern']}\n  它里面:{literal}"
    )


@pytest.mark.parametrize("location,symbol,reader", [
    ("plugins/bundled/comfyui/tools/canvas_edit.py", "_PATH", _python_pattern),
    ("backend/app/domain/workbench/agent.py", "_NODE_REF", _python_pattern),
    ("electron/ipc-contract.cjs", "CANVAS_NODE", _js_regex_literal),
    ("electron/ipc-contract.cjs", "ANY_NODE", _js_regex_literal),
    ("electron/ipc-contract.cjs", "NODE_PATH", _js_regex_literal),
])
def test_每一处实现逐条跑契约的用例(location: str, symbol: str, reader: Any) -> None:
    """**这一条才是「两侧同时红」的机制**:用例来自契约,不认形状的地方逐条点名报出来。"""
    impl = _implementation_entry(location, symbol)
    shape = _shape(impl["shape"])
    source = reader(location, symbol)
    if reader is _js_regex_literal:
        source = _python_view_of_js(source)
    rx = re.compile(f"^(?:{source})$")
    wrong = [one for one in _cases(shape, "ok") if not rx.fullmatch(one)]
    loose = [one for one in _cases(shape, "bad") if rx.fullmatch(one)]
    assert not wrong, f"{location} 的 {symbol} 拒了契约说该收的:{wrong}\n  {shape['why']}"
    assert not loose, f"{location} 的 {symbol} 收了契约说该拒的:{loose}\n  {shape['why']}"


def test_两条形状只在裸单号这一点上不同() -> None:
    """契约的 `divergence` 说 `canvas_path` 比 `subgraph_path` 宽**一格、只在下界上**。

    这一段是可执行的,量的**只是两条正则的能力(能收哪些串)**,与「语料里各列了哪些用例」无关:
    在两张形状的用例并集上,两条判据只允许在「只有一段」的那些串上给出不同答案。谁哪天把它们
    的深度改成不一样(16 → 17),这里会红 —— 而那是**行为改动**,不是补用例。
    """
    wide, narrow = _shape("canvas_path"), _shape("subgraph_path")
    shared = sorted(set(_all_cases(wide)) & set(_all_cases(narrow)))
    assert shared, "两条形状一条共用用例都没有 —— 那样这一段量不到任何东西"
    #: 比 `bool`:**`re.Match` 之间 `!=` 恒为真**(它没有 `__eq__`,两个逐字段相同的 Match 也不相等)。
    differs = {
        one
        for one in shared
        if bool(_oracle(wide).fullmatch(one)) != bool(_oracle(narrow).fullmatch(one))
    }
    assert differs == {"12", "-3"}, (
        f"两条形状共用用例里的差别是 {sorted(differs)} —— 契约的 divergence 说的是「只有一段」那两条"
        f"(`12` / `-3`)。\n  深度、负号的位置、段里几位数,那两个维度都必须一样。"
    )
    #: 用例本身也要钉住上限:两条形状的 ok 里最后一条都正好 16 段,拒的那条 20 段。
    for shape in (wide, narrow):
        assert len(_cases(shape, "ok")[-1].split(":")) == 16, f"{shape['name']} 少了 16 段那一条"
        assert len(_cases(shape, "bad")[-1].split(":")) == 20, f"{shape['name']} 少了「太深了」那一条"


# --- 真入口:插件的 canvas_edit ---------------------------------------------------------------


@pytest.fixture
def plugin_tools(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """把插件的 `tools/` 挂上 sys.path —— 和 `test_comfyui_plugin_agent.py` 同一个办法。"""
    saved = {name: sys.modules.pop(name) for name in ("canvas_edit", "canvas", "graph", "convert", "subgraphs")
             if name in sys.modules}
    sys.path.insert(0, str(TOOLS))
    try:
        yield
    finally:
        sys.path.remove(str(TOOLS))
        for name in ("canvas_edit", "canvas", "graph", "convert", "subgraphs"):
            sys.modules.pop(name, None)
        sys.modules.update(saved)


def _nested_graph() -> dict:
    """一张**每一层都真有一个子图**的小图:`12` → 定义 `deep`,里面 `5` → 定义 `deeper`,里面 `3`。

    空图验不了「收下」那一半:`layer_arg` 过了形状那一关之后还要真的走到那一层 ——
    形状与「画布上真有这么一个节点」是两件事,所以要分开验。
    """
    return {
        "nodes": [{"id": 12, "type": "deep"}],
        "links": [],
        "definitions": {"subgraphs": [
            {"id": "deep", "nodes": [{"id": 5, "type": "deeper"}], "links": []},
            {"id": "deeper", "nodes": [{"id": 3, "type": "KSampler"}], "links": []},
        ]},
        "extra": {},
    }


def _empty_graph() -> dict:
    return {"nodes": [], "links": [], "definitions": {"subgraphs": []}, "extra": {}}


def _said(error: BaseException, zh: str, en: str) -> bool:
    """插件那句报错说的是哪一句。它两种语言都带着(`_Bad` 有 `.zh` / `.en`),按哪一个比都行。

    **不按 `str(error)` 比**:那要看这次跑在哪种 locale 下(`say` 按它挑),而这条测试量的是
    「拒在哪一关」,不是「用哪种话说」。
    """
    return zh in getattr(error, "zh", "") or en in getattr(error, "en", "")


def test_插件的画布引用_真入口逐条跑契约的用例(plugin_tools: None) -> None:
    """`canvas_edit._Planner.layer_arg` 是 `_PATH` 的真调用方(没给 `graph` 时那个节点指哪一层)。

    断言的是**它的报错 / 它的返回值**,不是那行正则 —— 正则对了而调用点用错了是真发生过的事。
    形状与「画布上真有这么一个节点」是两件事,所以分开看:

    - `12`(那张图里真有的那一个)过形状、并真的走到 `deep` 那一层;
    - 其余每一条要么落在 `_walk` 上(「不是子图节点」= 形状过了),要么落在形状那一关
      (「要写子图节点的编号」= 形状没过)—— 报错落在哪一关才是这一条要验的。
    """
    module = importlib.import_module("canvas_edit")
    shape = _shape("canvas_path")
    planner = module._Planner(dict(_nested_graph()), {})  # noqa: SLF001 — 契约测试要的就是这一层

    #: 那张图里真走得通的:根图上的 `12` 是一个子图节点,它里面那个 `5` 又是一个。
    assert planner.layer_arg("12") == "deep", "根图上的 12 是一个子图节点,它指的就是那一层"
    assert planner.layer_arg("12:5") == "deeper"
    assert planner.layer_arg("#12") == "deep", "带 `#` 的写法也认(它先 lstrip 一次)"

    #: 形状收下、而这张图上落空的:报的必须是「不是子图节点」,也就是**过了形状那一关**。
    walked = [one for one in _cases(shape, "ok") if one.lstrip("#") not in ("12", "12:5")]
    for one in walked:
        with pytest.raises(module._Bad) as refused:
            planner.layer_arg(one)
        assert _said(refused.value, "不是子图节点", "is not a subgraph node"), (
            f"{one} 是一个画布引用,该在「走到哪一层」上落空;插件报的是「{refused.value}」"
        )

    #: 契约量的是**形状本身**,入口另有一层宽松(它先 `strip()`),所以这几条是这个入口写明的例外:
    #: 空串 = 「没给 graph」,带首尾空白 = 和去掉空白一样。它们在契约的 `bad` 里,因为**形状**不收;
    #: 而入口收 —— 这两件事不是一回事,所以在这里逐条点名,而不是把它们从 `bad` 里删掉。
    for one, expected in (("", None), (" 12", "deep"), ("12 ", "deep")):
        assert one in _cases(shape, "bad"), f"{one!r} 在契约里是拒的 —— 这条例外写歪了"
        assert planner.layer_arg(one) == expected

    for one in _cases(shape, "bad"):
        if one.strip() == "12" or one == "":
            continue
        with pytest.raises(module._Bad) as refused:
            planner.layer_arg(one)
        assert not _said(refused.value, "不是子图节点", "is not a subgraph node"), (
            f"{one} 不该过形状那一关,插件却把它当成了一个引用(报的是「{refused.value}」)"
        )


# --- 真入口:后端的 comfy_locate --------------------------------------------------------------


def test_工作台智能体的定位_真入口逐条跑契约的用例() -> None:
    """`workbench_agent.locate` 的 `node` 是 `_NODE_REF` 的真调用方。

    这里只跑形状那一半(剩下的要一台连着的工作台),但形状正是断过一次的那一半:桥当年拒了
    `12:5`,而 `comfy_locate` 认它 —— 两侧对同一串给的答案不同。
    """
    from app.domain.workbench import agent as workbench_agent

    shape = _shape("canvas_path")
    pattern = workbench_agent._NODE_REF  # noqa: SLF001 — 契约测试直接看那一处落点
    assert _unanchored(pattern.pattern) == shape["pattern"]
    for one in _cases(shape, "ok"):
        assert pattern.match(one), f"{one} 是画布上的一个引用,comfy_locate 却拒了它"
    for one in _cases(shape, "bad"):
        assert not pattern.match(one), f"{one} 不是一个画布引用,comfy_locate 却收了它"
