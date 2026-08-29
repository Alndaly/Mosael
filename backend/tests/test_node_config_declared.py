from __future__ import annotations

import ast
from pathlib import Path

from app.domain.workflows import NODE_TYPES
from app.domain.generation.operations import parse_source_assets

"""节点声明的配置项,必须覆盖执行器真正读取的那些。

这条约束来自一个**沉默**的缺口:`ai_generate` 的执行器一直在读 `negative_prompt` /
`parameters` / `source_assets`,但节点类型里没声明它们 —— 于是编辑器渲染不出输入框、
AI 助手也不知道它们存在。表现不是报错,而是「工作流里做不出竖屏视频」,而代码看上去哪儿都对。

声明即接口:执行器读什么,节点就得声明什么,否则那份能力对用户不存在。
"""

EXECUTORS_DIR = Path(__file__).resolve().parents[1] / "app" / "domain" / "workflows" / "executors"

#: 执行器读得到、但**刻意**不作为用户可填项的键。加进来必须写明理由。
NOT_USER_CONFIGURABLE: dict[str, set[str]] = {
    # 循环体/子图是内嵌子图,由画布编辑,不是表单字段。
    "loop_foreach": {"body"},
    "loop_while": {"body"},
    "subgraph": {"body"},
}


def _executor_config_keys() -> dict[str, set[str]]:
    """扫执行器源码里的 `config.get("x")`,按 @register("节点类型") 归组。"""
    found: dict[str, set[str]] = {}
    for path in sorted(EXECUTORS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            registered = [
                deco.args[0].value
                for deco in node.decorator_list
                if isinstance(deco, ast.Call)
                and isinstance(deco.func, ast.Name)
                and deco.func.id == "register"
                and deco.args
                and isinstance(deco.args[0], ast.Constant)
                and isinstance(deco.args[0].value, str)
            ]
            if not registered:
                continue
            keys: set[str] = set()
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "get"
                    and isinstance(sub.func.value, ast.Name)
                    and sub.func.value.id == "config"
                    and sub.args
                    and isinstance(sub.args[0], ast.Constant)
                    and isinstance(sub.args[0].value, str)
                ):
                    keys.add(sub.args[0].value)
            for node_type in registered:
                found.setdefault(node_type, set()).update(keys)
    return found


def test_executors_only_read_declared_config() -> None:
    missing: list[str] = []
    for node_type, keys in _executor_config_keys().items():
        declared = set(NODE_TYPES.get(node_type, {}).get("config", {}))
        allowed = NOT_USER_CONFIGURABLE.get(node_type, set())
        for key in sorted(keys - declared - allowed):
            missing.append(f"{node_type}.{key}")
    assert not missing, (
        "执行器读了没声明的配置项 —— 这些能力在编辑器和 AI 助手眼里根本不存在:\n  "
        + "\n  ".join(missing)
    )


def test_the_scan_actually_finds_something() -> None:
    """防止扫描器本身失效(改了装饰器/取值写法后扫不到,上面那条就会永远绿)。"""
    found = _executor_config_keys()
    assert "ai_generate" in found
    assert {"provider", "model", "kind", "prompt", "parameters"} <= found["ai_generate"]


def _ids(value, kind="video") -> list[str]:
    return [item["asset_id"] for item in parse_source_assets(value, kind=kind)]


def test_reference_assets_accept_a_template_string() -> None:
    """参考图/首帧要能接上游节点的输出({{gen-1.asset_id}}),而模板字段只会给到字符串。
    只认列表的话这个字段在编辑器里就没法用。"""
    assert _ids("a\nb") == ["a", "b"]
    assert _ids("a, b") == ["a", "b"]
    assert _ids("a，b") == ["a", "b"], "中文逗号也要认——中文输入法下这是常态"
    assert _ids(["a", " ", "b"]) == ["a", "b"]
    assert _ids("") == []
    assert _ids(None) == []


def test_模板字符串里也能写角色() -> None:
    """`{{gen-1.asset_id}}:last_frame` —— 上游产出的那张图当尾帧。
    不支持的话,工作流里就只能做首帧,而首尾帧恰恰是工作流最想串的形状。"""
    assert parse_source_assets("a:last_frame\nb", kind="video") == [
        {"asset_id": "a", "role": "last_frame"},
        {"asset_id": "b", "role": "first_frame"},
    ]


def test_不写角色时按介质兜底() -> None:
    """图生视频的那张图是首帧,图生图的那张图是参考 —— 这是两种介质里最常见的那个意思。"""
    assert parse_source_assets("a", kind="video")[0]["role"] == "first_frame"
    assert parse_source_assets("a", kind="image")[0]["role"] == "reference_image"


def test_角色写错了当场拦住() -> None:
    """默默当成首帧的话,用户会拿到一段「怎么改提示词都不对」的视频。"""
    import pytest

    from app.domain.generation.operations import GenerationDomainError

    with pytest.raises(GenerationDomainError, match="未知的素材角色"):
        parse_source_assets("a:头一帧", kind="video")


def test_素材和时间线字段自己会声明类型() -> None:
    """界面靠字段类型决定给不给素材选择器、画不画缩略图、连线类型对不对得上。

    这份知识此前是**前端自己抄的一张表**(features/workflows/analyze.ts 的 INPUT_TYPES),
    于是三件事一起坏:

      · 「素材」节点本身就漏了 —— 它整个存在的意义就是指向一份素材,却拿不到素材选择器,
        用户只能手打一串十六进制;
      · asset_tag / asset_update / browser_upload 也漏了;
      · **插件节点永远不可能被那张表覆盖** —— 它们是运行时才知道的。

    加一种节点忘了补表不会报错,只是安静地少了选择器和校验。所以改成按字段名推,这条钉住它。
    """
    from app.domain.workflows import NODE_TYPES, config_data_type

    for name, spec in NODE_TYPES.items():
        for key, meta in (spec.get("config") or {}).items():
            if key.endswith("asset_id") or key.endswith("asset_ids"):
                assert config_data_type(key, meta) == "asset", f"{name}.{key} 没被认成素材"
            if key.endswith("sequence_id"):
                assert config_data_type(key, meta) == "sequence", f"{name}.{key} 没被认成时间线"


def test_显式声明压过命名约定() -> None:
    """约定覆盖不到的字段(名字不叫 asset_id 但装的就是素材)要能显式指定,
    否则这条约定就从"省事"变成了"挡路"。"""
    from app.domain.workflows import config_data_type

    assert config_data_type("whatever", {"data_type": "asset"}) == "asset"
    assert config_data_type("whatever", {}) == ""


def test_节点类型接口把类型发出去() -> None:
    """推出来了但没发给前端,等于没推。"""
    from app.api.routes.workflows import _with_data_type

    assert _with_data_type("asset_id", {"type": "template"})["data_type"] == "asset"
    # 推不出来的字段不该凭空多一个空 data_type —— 那会让前端以为它被声明过。
    assert "data_type" not in _with_data_type("prompt", {"type": "template"})


def test_每个配置字段都有中文标签() -> None:
    """界面上直接露出英文键名是不该发生的事。

    这份知识此前是前端手抄的一张表(WorkflowsView 的 FIELD_LABEL_KEYS),81 个键只覆盖了 28 个
    —— 剩下 55 个在中文界面上就显示 `session`、`selector`、`timeout_ms`、`temperature`。
    而且**插件节点永远不可能被那张表覆盖**,它们是运行时才知道的。

    这是同一个形状第三次出现(智能体的角色表、字段类型表、标签表):一份该住在声明里的知识
    被抄到消费方那边,加东西时漏掉不报错,只是界面上默默露出一个英文单词。
    """
    from app.domain.workflows import NODE_TYPES, config_label

    missing = [
        f"{name}.{key}"
        for name, spec in NODE_TYPES.items()
        for key, meta in (spec.get("config") or {}).items()
        if not config_label(key, meta)
    ]
    assert missing == [], f"这些字段会在界面上露出英文键名:{missing}"


def test_节点自己的_label_压过共用表() -> None:
    """`selector` 在六种浏览器节点里是同一个意思,所以按键名给;某个节点要特别说法时
    得能覆盖,否则共用表就从"省事"变成了"挡路"。"""
    from app.domain.workflows import config_label

    #: 表里存的是 key(出口才翻,见 core/i18n)——这里断言的是「用了共用表那一条」,
    #: 而不是那条长什么样。
    assert config_label("selector", {}) == "wfField_selector"
    assert config_label("selector", {"label": "要点的元素"}) == "要点的元素"


def test_标签真的发到接口上() -> None:
    """在后端算好但没发出去,等于没算。

    **打接口,不打内部函数** —— 中间还隔着一层翻译,而用户要的是那句人话:内部返回 key、
    出口忘了翻的话,界面上就是一串 wfField_selector,而只看内部函数的测试照样是绿的。
    """
    from tests.util import fresh_client

    client = fresh_client()
    for header, expected in (("zh-CN", "元素选择器"), ("en-US", "Selector")):
        types = client.get("/api/workflows/node-types", headers={"Accept-Language": header}).json()
        click = next(one for one in types if one["type"] == "browser_click")
        assert click["config"]["selector"]["label"] == expected, f"{header} 下标签没翻出来"


def test_名字到值的映射不该让用户手写_JSON() -> None:
    """入参映射、请求头、具名输出、启动参数……绝大多数 object 字段其实是「名字 → 值」,
    而值往往是上游节点的引用(`{{llm-1.text}}`)。

    让用户对着一个 `{}` 手写 JSON,键名要背、引号逗号要记,而**写错了直到运行才知道**:
    少个引号是解析失败(还算好),引用名写错则一路静默传个空值下去。
    """
    from app.domain.workflows import NODE_TYPES, config_editor

    for name, spec in NODE_TYPES.items():
        for key, meta in (spec.get("config") or {}).items():
            if meta.get("type") != "object":
                continue
            editor = config_editor(key, meta)
            assert editor in {"map", "json"}, f"{name}.{key} 没说清用哪种编辑器"


def test_只有真正自由结构的才留原始_JSON() -> None:
    """json_schema 是一份 schema,天然嵌套,拍平成键值对是错的。**默认给 map**,
    例外自己声明 —— 这样新加的 object 字段自动就有友好编辑器,而不是等谁记得来补。"""
    from app.domain.workflows import config_editor

    assert config_editor("json_schema", {"type": "object"}) == "json"
    assert config_editor("inputs", {"type": "object"}) == "map"
    assert config_editor("whatever", {"type": "object", "editor": "json"}) == "json"
    # 非 object 不归它管。
    assert config_editor("prompt", {"type": "template"}) == ""

