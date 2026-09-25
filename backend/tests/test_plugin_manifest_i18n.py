"""插件清单里给人看的文字必须能跟着界面语言走。

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。

这个仓库里数据目录的多语言一律是「领域里存 key,出口才翻」—— 文案进 `core/i18n.MESSAGES`,
清单里只留 key。**插件清单不能这么办**:插件是第三方写的,它没法往我们的表里加词条。

所以换一条路:**翻译贴着它翻译的那个东西写**,一段给人看的文字既可以是普通字符串,
也可以是 `{"zh": …, "en": …}`。不写成清单顶上的一张 `{"config.X.label": …}` 侧表,是因为
那种表的键要和别处对得上,而对不上时不会报错,只会让那一条永远显示原文 —— 这个项目在
「手抄一张表」上栽过好几次。

下面第二条钉的是**我们自己发的那几个插件**:它们是别人写插件时照抄的样板,样板上只有中文,
抄出来的插件在英文界面上就还是中文。
"""

from __future__ import annotations

RATCHET = True

import json
import re
from pathlib import Path
from typing import Any

from app.core.i18n import set_current_locale
from app.domain.plugins.manifest import parse, text_of

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "plugins" / "examples"
#: 随应用发的插件(ComfyUI)也是我们自己发的 —— 同一条规矩。
BUNDLED = ROOT / "plugins" / "bundled"
MANIFEST_NAME = "mosael.plugin.json"
CJK = re.compile(r"[一-鿿]")


def _manifests() -> list[tuple[str, dict[str, Any]]]:
    paths = sorted([*EXAMPLES.glob(f"*/{MANIFEST_NAME}"), *BUNDLED.glob(f"*/{MANIFEST_NAME}")])
    return [(p.parent.name, json.loads(p.read_text(encoding="utf-8"))) for p in paths]


def _human_texts(raw: dict[str, Any]) -> list[tuple[str, Any]]:
    """清单里所有**给人看的**字段。位置写死 —— 不扫全树,免得把 id、路径也当成文案。"""
    out: list[tuple[str, Any]] = [("name", raw.get("name"))]
    for i, skill in enumerate(raw.get("skills") or []):
        out.append((f"skills[{i}].description", skill.get("description")))
    instance = raw.get("instance") or {}
    if instance.get("name_template"):
        out.append(("instance.name_template", instance["name_template"]))
    for group in ("config", "credentials"):
        for spec in instance.get(group) or []:
            where = f"instance.{group}.{spec.get('key')}"
            for key in ("label", "help"):
                if spec.get(key):
                    out.append((f"{where}.{key}", spec[key]))
            for option in spec.get("options") or []:
                out.append((f"{where}.options.{option.get('value')}.label", option.get("label")))
    tools = raw.get("tools") if isinstance(raw.get("tools"), dict) else {}
    for tool in tools.get("declare") or []:
        out.append((f"tools.{tool.get('name')}.description", tool.get("description")))
        node = tool.get("node") or {}
        if node.get("label"):
            out.append((f"tools.{tool.get('name')}.node.label", node["label"]))
        for key, spec in ((tool.get("input_schema") or {}).get("properties") or {}).items():
            if spec.get("description"):
                out.append((f"tools.{tool.get('name')}.args.{key}.description", spec["description"]))
    return out


def test_一段文案可以是字符串也可以是按语言分的对象() -> None:
    set_current_locale("en")
    assert text_of("Start directory") == "Start directory"
    assert text_of({"zh": "起始目录", "en": "Start directory"}) == "Start directory"
    set_current_locale("zh")
    assert text_of({"zh": "起始目录", "en": "Start directory"}) == "起始目录"


def test_只写了一种语言时给原文而不是空白() -> None:
    """插件作者只写中文,英文界面上看到中文 —— 总好过看到一片空白。"""
    set_current_locale("en")
    assert text_of({"zh": "起始目录"}) == "起始目录"
    assert text_of({"ja": "開始ディレクトリ"}) == "開始ディレクトリ"
    assert text_of(None) == ""


def test_我们自己发的插件每一句中文都配了英文() -> None:
    """样板上只有中文的话,照着它写的插件在英文界面上也只有中文。"""
    missing: list[str] = []
    for name, raw in _manifests():
        for where, value in _human_texts(raw):
            if isinstance(value, str) and CJK.search(value):
                missing.append(f"{name}: {where}")
            elif isinstance(value, dict) and not str(value.get("en") or "").strip():
                missing.append(f"{name}: {where}(缺 en)")
    assert not missing, "这些文案在英文界面上还是中文:\n" + "\n".join(missing)


def test_示例插件都能解析成能跑的东西() -> None:
    """曾经有两个示例停在旧清单形状上,解析出来是 `entry=''`、零个工具 —— 而且一声不吭。"""
    for name, raw in _manifests():
        manifest = parse(raw, name)
        if manifest.is_mcp:
            assert manifest.runtime.command or manifest.runtime.url, f"{name} 是 MCP 插件却没说怎么连"
        else:
            assert manifest.runtime.entry, f"{name} 是脚本插件却没有入口"


def test_这道棘轮扫得到东西() -> None:
    """假阴性比红更危险:哪天目录改了名,上面几条会一起真空通过。"""
    assert len(_manifests()) >= 3
    assert sum(len(_human_texts(raw)) for _, raw in _manifests()) >= 20


def test_文档链接只认_http() -> None:
    """那个链接是直接交给用户浏览器打开的 —— `javascript:` 是一条从第三方清单直通浏览器的路。

    这里不是在防御格式,是在防御来源:清单是别人写的。
    """
    from app.domain.plugins.manifest import parse

    base = {"id": "x", "name": "X", "version": "1"}
    for good in ("https://docs.example.com/", "http://example.com/a"):
        assert parse({**base, "homepage": good}, "").homepage == good

    for bad in ("javascript:alert(1)", "file:///etc/passwd", "ftp://x/y", "docs.example.com", ""):
        assert parse({**base, "homepage": bad}, "").homepage == "", bad


def test_参数就叫title或description时_不被当成说明文字() -> None:
    """`properties` 下面的键是**字段名**。此前整棵树里凡是叫 title / description 的双语对象都当
    说明文字翻 —— 于是一个名叫 `title` 的参数,整个 schema 被换成了一个字符串(Remotion 插件
    「讲解视频」的标题参数就这样丢了类型;发布类插件的 `description` 参数同理)。"""
    from app.domain.plugins.manifest import parse

    title_schema = {"type": "string", "description": {"zh": "视频标题", "en": "Video title"}}
    raw = {
        "id": "x.y", "manifest_version": 1, "name": "X", "version": "1", "_path": "/tmp/x",
        "tools": {"declare": [{
            "name": "t",
            "input_schema": {
                "type": "object",
                "title": {"zh": "整个输入", "en": "The whole input"},
                "properties": {"title": title_schema, "description": {"type": "string"}, "ref": {"$ref": "#/$defs/title"}},
                "$defs": {"title": title_schema},
            },
        }]},
    }
    set_current_locale("en")
    schema = parse(raw, "x").declared_tools[0]["input_schema"]
    assert schema["properties"]["title"] == {"type": "string", "description": "Video title"}
    assert schema["properties"]["description"] == {"type": "string"}
    assert schema["$defs"]["title"] == {"type": "string", "description": "Video title"}
    # 真正的关键字 title(描述整个 schema 的那个)照旧翻。
    assert schema["title"] == "The whole input"


def test_input_schema_里的说明也要定语言() -> None:
    """参数说明写成双语对象时,界面上不能出现 `[object Object]`。

    工具自己的 description 一直是翻的,而**参数的那一份不是** —— 于是试运行面板里每个参数
    标签后面跟着一句 `[object Object]`。作者按清单里到处都能用的写法写了双语,而这一处偏偏
    不认;这种"大部分地方能用"的不一致最难自己发现,因为写的人根本不会怀疑它。
    """
    from app.domain.plugins.manifest import parse

    raw = {
        "id": "x.y",
        "manifest_version": 1,
        "name": "X",
        "version": "1",
        "_path": "/tmp/x",
        "tools": {
            "declare": [
                {
                    "name": "t",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": {"zh": "路径", "en": "Path"}},
                            "plain": {"type": "string", "description": "已经是字符串"},
                        },
                    },
                }
            ]
        },
    }
    set_current_locale("zh")
    props = parse(raw, "x").declared_tools[0]["input_schema"]["properties"]
    assert props["path"]["description"] == "路径"
    # 两种语言都断言:只断言一种的话,它可能只是碰巧和当前语言一致 —— 而"根本没翻"
    # 在那种写法下同样能通过。
    set_current_locale("en")
    assert parse(raw, "x").declared_tools[0]["input_schema"]["properties"]["path"]["description"] == "Path"
    # 普通字符串原样不动 —— 大多数插件是这么写的,别为了修双语把它们弄坏。
    assert props["plain"]["description"] == "已经是字符串"
    # type 这类数据一个字不动。
    assert props["path"]["type"] == "string"


def test_嵌套层里的说明同样要定语言() -> None:
    """只认 `properties` 那一层等于换个写法就又漏了 —— JSON Schema 里说明文字可以出现在
    items、oneOf、$defs 的任何一层,而那时的表现和这次一模一样:一句 `[object Object]`。"""
    from app.domain.plugins.manifest import parse

    raw = {
        "id": "x.y",
        "manifest_version": 1,
        "name": "X",
        "version": "1",
        "_path": "/tmp/x",
        "tools": {
            "declare": [
                {
                    "name": "t",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "items": {
                                "type": "array",
                                "items": {"type": "string", "description": {"zh": "一项", "en": "One"}},
                            }
                        },
                    },
                }
            ]
        },
    }
    set_current_locale("zh")
    schema = parse(raw, "x").declared_tools[0]["input_schema"]
    assert schema["properties"]["items"]["items"]["description"] == "一项"


def _looks_like_a_stringified_dict(value: object) -> bool:
    """`str({"zh": …})` 的样子。界面上就是一行 `{'zh': '从百度网盘导入', 'en': …}`。"""
    return isinstance(value, str) and bool(re.match(r"^\{['\"](zh|en)['\"]:", value.strip()))


def _every_string(value: object, path: str = "") -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(path, value)]
    if isinstance(value, dict):
        return [pair for key, item in value.items() for pair in _every_string(item, f"{path}.{key}")]
    if isinstance(value, list):
        return [pair for index, item in enumerate(value) for pair in _every_string(item, f"{path}[{index}]")]
    return []


def test_工作流节点上的文字也要解出来() -> None:
    """**声明了翻译不等于有人去解。**

    这条补的是消费端。清单那边一直是对的,而工作流节点目录用的是裸 `str()` —— 一个
    `{"zh": …, "en": …}` 就被按 Python 的样子印出来,节点列表里赫然一行
    `{'zh': '从百度网盘导入', 'en': 'Import from Baidu…'}`。

    `input_schema` 里的参数说明此前栽过同一下(见上一条,当时是 `[object Object]`),
    所以这里不再逐个字段点名,而是把整份节点元数据摊平了扫 —— 以后新增字段自动被盖住。
    """
    from app.domain.plugins.nodes import node_meta

    checked = 0
    for name, raw in _manifests():
        for tool in (raw.get("tools") or {}).get("declare") or []:
            if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
                continue
            meta = node_meta({**tool, "instance_name": "X"})
            for where, text in _every_string(meta):
                assert not _looks_like_a_stringified_dict(text), f"{name} {tool['name']}{where}: {text}"
            checked += 1
    assert checked >= 3, "没扫到几个声明式工具 —— 这条会真空通过"


def test_节点标签跟着界面语言走() -> None:
    """光是"没印出字典"还不够 —— 得真的换语言。"""
    from app.domain.plugins.nodes import node_meta

    tool = {
        "name": "pan_import",
        "description": {"zh": "把文件拉进素材库", "en": "Pull a file into the library"},
        "node": {"label": {"zh": "从百度网盘导入", "en": "Import from Baidu Netdisk"}},
        "input_schema": {"properties": {"fs_id": {"type": "string",
                                                  "description": {"zh": "网盘文件 id", "en": "netdisk file id"}}}},
    }
    try:
        set_current_locale("zh")
        zh = node_meta(tool)
        set_current_locale("en")
        en = node_meta(tool)
    finally:
        set_current_locale("zh")

    assert zh["label"] == "从百度网盘导入" and en["label"] == "Import from Baidu Netdisk"
    assert zh["description"] != en["description"]
    assert zh["config"]["fs_id"]["description"] == "网盘文件 id"
    assert en["config"]["fs_id"]["description"] == "netdisk file id"


class Test插件自己处理多语言:
    """清单里的文案我们替它挑;工具**跑出来**的那些字只有插件自己写得出 —— 所以得让它知道
    读的人用什么语言。"""

    def test_按主语言匹配_不按整串相等(self) -> None:
        """清单里的键是作者写的,他没有义务用我们这两个短标签(真见过 `en-US`)。"""
        from app.domain.plugins.manifest import text_of

        value = {"zh-CN": "起始目录", "en-US": "Start directory"}
        assert text_of(value, "zh") == "起始目录"
        assert text_of(value, "en") == "Start directory"
        assert text_of({"EN": "Upper"}, "en") == "Upper"

    def test_挑不到时先退作者声明的原文语言(self) -> None:
        from app.domain.plugins.manifest import parse, text_of

        value = {"de": "Startverzeichnis", "en": "Start directory"}
        #: 没声明原文语言:退到部署缺省(zh)→ 也没有 → 作者写的第一条。
        assert text_of(value, "fr") == "Startverzeichnis"
        #: 声明了原文是英文:退到英文,而不是碰巧排在前面的那条。
        assert text_of(value, "fr", author_locale="en") == "Start directory"
        manifest = parse(
            {"id": "x", "name": {"de": "Werkzeug", "en": "Toolkit"}, "version": "1", "default_locale": "en",
             "runtime": {"kind": "process", "entry": "main.py"}},
            "/tmp/x",
        )
        assert manifest.default_locale == "en"
        assert manifest.text({"de": "A", "en": "B"}, "fr") == "B"

    def test_进程插件拿得到这次要说的语言(self, monkeypatch, tmp_path) -> None:
        """请求体和环境变量各给一份:读哪个都行。"""
        import json

        from app.core.i18n import set_current_locale
        from app.domain.plugins import runtime
        from app.domain.plugins.manifest import LOCALE_ENV

        seen: dict = {}

        class _Result:
            returncode = 0
            stdout = json.dumps({"ok": True, "output": {}})
            stderr = ""

        def fake_run(args, **kwargs):
            seen["request"] = json.loads(kwargs["input"])
            seen["env"] = kwargs["env"]
            return _Result()

        entry = tmp_path / "main.py"
        entry.write_text("", encoding="utf-8")
        monkeypatch.setattr(runtime, "run_logged", fake_run)
        monkeypatch.setattr(runtime, "base_python", lambda: "/usr/bin/python3")
        set_current_locale("en")
        try:
            runtime.execute_tool(tmp_path, "main.py", "fetch", {"q": "x"})
        finally:
            set_current_locale("zh")
        assert seen["request"]["locale"] == "en"
        assert seen["env"][LOCALE_ENV] == "en"
        #: 输入照旧原样交给插件 —— 语言是**另一样东西**,不混进它的参数里。
        assert seen["request"]["input"] == {"q": "x"}

    def test_每条调用路径都告诉插件这次说哪种语言(self) -> None:
        """棘轮:进程、MCP·stdio、MCP·http 三条路都要带上。漏一条的表现是那种形态的插件
        永远只会说一种语言,而没有任何地方会报错。"""
        import pathlib

        domain = pathlib.Path(__file__).resolve().parents[1] / "app" / "domain" / "plugins"
        runtime = (domain / "runtime.py").read_text(encoding="utf-8")
        bridge = (domain / "mcp_bridge.py").read_text(encoding="utf-8")
        #: 认的是**代码里用到了那个常量**(源码里写的是 LOCALE_ENV,不是它的值)。
        assert "LOCALE_ENV: locale" in runtime and '"locale": locale' in runtime, "进程插件那条"
        assert "LOCALE_ENV: get_current_locale()" in bridge, "MCP stdio 那条"
        assert 'setdefault("Accept-Language"' in bridge, "MCP http 那条"

    def test_我们自己发的插件都说得出原文是哪种语言(self) -> None:
        """`default_locale` 不是必填(不写就退到作者写的第一条),但样板要摆在那儿。"""
        import json
        import pathlib

        plugins = pathlib.Path(__file__).resolve().parents[2] / "plugins"
        missing = [
            path.parent.name
            for path in sorted([*plugins.glob("examples/*/mosael.plugin.json"), *plugins.glob("bundled/*/mosael.plugin.json")])
            if not str(json.loads(path.read_text(encoding="utf-8")).get("default_locale") or "").strip()
        ]
        assert not missing, f"这几个示例插件没声明原文语言:{missing}"
