"""结构性约束:**自由文本字段必须声明成 `template`。**

因为引擎**本来就对每个字符串值做变量替换** —— `workflows.interpolate` 走整个 config 递归,
不看声明的类型。所以一个自由文本字段写 `type: "string"` 不是"它不支持变量",而是
**声明落后于实现**:运行时认 `{{node.key}}`,而编辑器照着声明给了个普通输入框,
于是那一格没有 `@` 引用菜单,用户也就无从知道这里能填变量。

用户的原话是「我注意到很多节点的输入框都不支持 @ 这是怎么回事」。答案就是这个:
`@` 挂在 `type === "template"` 上,而七个本该是 template 的字段被写成了 string ——
llm.stop、json_extract.path、text_transform.find / replace、browser_open.session_name、
browser_extract.attribute、llm.json_schema_name。它们的共同点是**都是自由文本**。

## 剩下的 string 是什么

两类,都不是自由文本:

  · 带 `options` 的枚举 —— 界面渲染成下拉,`@` 无从谈起;
  · **选择器背书的 id** —— 模型、档案、会话、账号这些,值从接口拉一张列表来选。
    界面的分支顺序是 options 优先于 type,所以把它们改成 template 也不会变成文本框,
    改了等于白改。它们在下面的 `_PICKER_KEYS` 里。

那张名单按**键名**列,不是逐节点列:`session` 在九个浏览器节点里是同一个意思,逐节点写
就是又抄了一张表。名单只减不增 —— 加一条意味着又多了一个"用户以为能填变量、实际给了个
下拉"或者反过来的地方。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

#: 值来自一张接口拉来的列表,界面渲染成选择器(options 优先于 type)。**只减不增。**
_PICKER_KEYS = {
    "profile_id",
    "model",
    "provider",
    "plugin_id",
    "tool_name",
    "account_id",
    "voice_id",
    "workflow_id",
    "session",
    # 语音合成的引擎与该引擎下的音色:两份都是现查的接口清单(/api/tts/engines、
    # /api/tts/voices),和上面的 model / voice_id 同一类。加进来是因为**新增了一个真正的
    # 选择器**,不是拿这张表当规避手段 —— 界面里 options 优先于 type,把它们声明成 template
    # 也只会得到同一个下拉,而 `@` 无从谈起。
    "engine",
    "engine_voice",
    # 资源号跟着音色一起被填上(选音色时自动写入),用户不手打,所以也不是自由文本。
    "engine_voice_resource",
}


def test_自由文本字段都声明成了template() -> None:
    from app.domain.workflows import NODE_TYPES

    offenders = [
        f"{name}.{key}"
        for name, spec in NODE_TYPES.items()
        for key, meta in (spec.get("config") or {}).items()
        if (meta or {}).get("type", "string") == "string"
        and not (meta or {}).get("options")
        and not (meta or {}).get("plugin_instances")
        and key not in _PICKER_KEYS
    ]
    assert not offenders, (
        "这些是自由文本字段,却声明成 string —— 引擎对它们本来就做 {{}} 替换,"
        "而编辑器照着声明给了个普通输入框,那一格没有 @:\n"
        + "\n".join(f"  {one}" for one in offenders)
    )


def test_引擎确实对普通字符串也做替换() -> None:
    """上面那条的**前提**。前提要是不成立,那条规则就只是个人偏好。

    这里直接验引擎:一个没被声明成 template 的键,照样会被 interpolate 换掉。
    """
    from app.domain.workflows import interpolate

    context = {"llm-1": {"text": "换进来了"}}
    assert interpolate({"随便什么键": "{{llm-1.text}}"}, context) == {"随便什么键": "换进来了"}
    # 嵌套结构也走同一条路 —— 所以 object 型字段里的值同样认变量。
    assert interpolate({"a": ["{{llm-1.text}}"]}, context) == {"a": ["换进来了"]}


def test_选择器名单里没有过期的条目() -> None:
    """名单里的键要是已经没有一个节点在用了,就该划掉 —— 留着它会豁免一个不存在的东西,
    下次真有字段漏了 template 时,读名单的人会以为"这里本来就有豁免"。"""
    from app.domain.workflows import NODE_TYPES

    used = {key for spec in NODE_TYPES.values() for key in (spec.get("config") or {})}
    stale = sorted(_PICKER_KEYS - used)
    assert not stale, f"这些键已经没有节点在用了,从 _PICKER_KEYS 里删掉:{stale}"
