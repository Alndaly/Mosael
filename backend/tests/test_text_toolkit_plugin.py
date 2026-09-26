"""Text Toolkit 插件:纯函数,直接 import 入口脚本验。

它是「写一个插件」文档里第一个被抄的样板 —— 所以这里钉的不只是算得对不对,还有清单是不是一个
**像样的节点**:输出拆成具名的口子、画板上只落那句话、技能里不许诺它没有的工具。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "examples" / "text-toolkit"


@pytest.fixture(scope="module")
def toolkit():
    spec = importlib.util.spec_from_file_location("text_toolkit_main", PLUGIN / "tools" / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Test字数:
    def test_中文一个字一个词_英文一个词一个词(self, toolkit) -> None:
        """此前 `[\\w一-鿿]+` 把一整串汉字算成一个词:「你好世界」是 1 个词。"""
        assert toolkit.word_count({"text": "你好世界"}, "zh")["words"] == 4
        assert toolkit.word_count({"text": "我爱Python编程"}, "zh")["words"] == 5
        assert toolkit.word_count({"text": "It's a well-known café test, 2 times."}, "en")["words"] == 7

    def test_朗读时长按语言算(self, toolkit) -> None:
        """中文每秒约 4.5 字;英文按词算(每分钟约 150 词)—— 按字符算的话英文长了两三倍。"""
        assert toolkit.word_count({"text": "一" * 45}, "zh")["estimated_seconds"] == 10.0
        english = toolkit.word_count({"text": "Hello world this is a test"}, "en")
        assert english["estimated_seconds"] == 2.4 and english["chars"] == 21
        assert "2.4" in english["summary"]

    def test_空文本(self, toolkit) -> None:
        assert toolkit.word_count({"text": ""}, "zh") | {"summary": ""} == {
            "chars": 0, "words": 0, "estimated_seconds": 0.0, "summary": ""}


class Test话题标签:
    def test_英文标签后面跟标点也认(self, toolkit) -> None:
        tags = toolkit.extract_hashtags({"text": "Love this #sunset! So #AI, much #café."}, "en")["hashtags"]
        assert tags == ["sunset", "AI", "café"]

    def test_成对的话题和单个井号的都认_按出现顺序(self, toolkit) -> None:
        tags = toolkit.extract_hashtags({"text": "上新啦 #好物# 去 #旅行 看看 #AI#和#ML"}, "zh")["hashtags"]
        assert tags == ["好物", "旅行", "AI", "ML"]

    def test_不是标签的井号不认(self, toolkit) -> None:
        text = "学 C# 和 F#,见 https://x.com/a#frag 与 &#123;,排名 #1,Issue #2024"
        assert toolkit.extract_hashtags({"text": text}, "zh")["hashtags"] == []

    def test_大小写不同算同一个(self, toolkit) -> None:
        assert toolkit.extract_hashtags({"text": "#AI #ai #Ai"}, "en")["hashtags"] == ["AI"]


class Test协议:
    def test_不认识的工具按语言说(self, toolkit, monkeypatch, capsys) -> None:
        import io

        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"tool": "nope", "input": {}, "locale": "zh"})))
        toolkit.main()
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is False and "nope" in out["error"] and "不认识" in out["error"]

    def test_input不是对象时说清楚_不是一个AttributeError(self, toolkit, monkeypatch, capsys) -> None:
        import io

        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"tool": "word_count", "input": ["x"], "locale": "en"})))
        toolkit.main()
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is False and "input" in out["error"] and "attribute" not in out["error"]


class Test清单:
    def manifest(self) -> dict:
        return json.loads((PLUGIN / "mosael.plugin.json").read_text(encoding="utf-8"))

    def test_输出拆成具名口子_画板上只落那句话(self, toolkit) -> None:
        """没写 outputs 的话整份返回装进一个 `output`,output_labels 里的名字全是空的,画板上是一张大 JSON 便签。"""
        for tool in self.manifest()["tools"]["declare"]:
            node = tool["node"]
            produced = set(getattr(toolkit, tool["name"])({"text": "#AI 你好"}, "zh"))
            assert set(node["outputs"]) == produced, tool["name"]
            assert set(node.get("output_labels", {})) <= set(node["outputs"])
            assert set(node["output_types"]) == set(node["outputs"])
            assert node["board_outputs"] == ["summary"] if tool["name"] == "word_count" else node["board_outputs"]

    def test_技能里不许诺没有的工具(self) -> None:
        skill = self.manifest()["skills"][0]["description"]
        assert "标题" not in skill["zh"] and "title" not in skill["en"].lower()
