"""Text Toolkit 插件:纯函数,直接 import 入口脚本验。

它是「写一个插件」文档里第一个被抄的样板 —— 所以这里钉的不只是算得对不对,还有清单是不是一个
**像样的节点**:输出拆成具名的口子、画板上只落那句话、技能里不许诺它没有的工具。
"""

from __future__ import annotations

import importlib.util
import json
import re
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


class Test断成字幕行:
    def test_一句一行_太长的在停顿处切_行尾逗号句号省掉(self, toolkit) -> None:
        text = "大家好，欢迎来到我的频道。今天聊一聊怎么把很长的口播稿，切成适合字幕的短句！准备好了吗？"
        out = toolkit.split_lines({"text": text, "max_chars": 12}, "zh")
        #: 「频道。」的句号悬在行外不占宽;太长的分句切成差不多长的两段,不是塞满一行、剩「播稿」吊着。
        assert out["lines"] == ["大家好，欢迎来到我的频道", "今天聊一聊怎么", "把很长的口播稿", "切成适合字幕的短句！", "准备好了吗？"]
        assert all(toolkit._width(line) <= 12 for line in out["lines"])
        assert not any(line.endswith(("，", "。")) for line in out["lines"])
        assert out["lines"][-1] == "准备好了吗？" and out["count"] == len(out["lines"])
        assert out["text"] == "\n".join(out["lines"])

    def test_英文不在词中间断_两个字母算半个字宽(self, toolkit) -> None:
        out = toolkit.split_lines({"text": "Let's get started with a quick demo, shall we?", "max_chars": "12"}, "en")
        joined = " ".join(out["lines"])
        assert joined.replace(",", "") == "Let's get started with a quick demo shall we?"
        assert all(toolkit._width(line) <= 12 for line in out["lines"])

    def test_小数和版本号不当句末_网址不从中间断(self, toolkit) -> None:
        assert toolkit.split_lines({"text": "版本 1.2 上线了", "max_chars": 20}, "zh")["lines"] == ["版本 1.2 上线了"]
        lines = toolkit.split_lines({"text": "see https://example.com/a/long/path ok", "max_chars": 8}, "en")["lines"]
        assert lines == ["see", "https://example.com/a/long/path", "ok"]

    def test_要保留标点就留着(self, toolkit) -> None:
        out = toolkit.split_lines({"text": "你好。再见。", "keep_punctuation": "true"}, "zh")
        assert out["lines"] == ["你好。", "再见。"]

    def test_每行宽度不是正整数就直说(self, toolkit) -> None:
        with pytest.raises(toolkit.ToolError, match="max_chars"):
            toolkit.split_lines({"text": "x", "max_chars": "0"}, "zh")


class Test截短:
    def test_没超就原样(self, toolkit) -> None:
        out = toolkit.truncate({"text": "短标题", "max_chars": 10}, "zh")
        assert out["text"] == "短标题" and out["removed"] == 0

    def test_省略号算在字数里_尽量停在停顿处(self, toolkit) -> None:
        out = toolkit.truncate({"text": "这是一个特别长的句子，用来测试截短到底好不好用", "max_chars": 15}, "zh")
        assert out["text"] == "这是一个特别长的句子…" and out["chars"] <= 15

    def test_英文不截半个词(self, toolkit) -> None:
        out = toolkit.truncate({"text": "How to cut a long video title without breaking words", "max_chars": 30}, "en")
        assert out["text"] == "How to cut a long video title…" and len(out["text"]) <= 30

    def test_省略号可以不要(self, toolkit) -> None:
        assert toolkit.truncate({"text": "一二三四五六七八九十", "max_chars": 5, "ellipsis": ""}, "zh")["text"] == "一二三四五"


class Test清理文案:
    def test_默认_去零宽_收空格空行_全角字母数字换半角_中文后的半角标点换全角(self, toolkit) -> None:
        out = toolkit.clean_text({"text": "  你好,世界!这是ＡＢＣ１２３\u200b 测试.  \n\n\n\n版本1.2  好"}, "zh")
        assert out["text"] == "你好，世界！这是ABC123 测试。\n\n版本1.2 好"

    def test_表情默认留着_连起来的那种不拆散(self, toolkit) -> None:
        family = "\U0001f468\u200d\U0001f469\u200d\U0001f467"
        assert toolkit.clean_text({"text": f"一家人{family}"}, "zh")["text"] == f"一家人{family}"
        assert toolkit.clean_text({"text": f"一家人{family}好", "remove_emoji": True}, "zh")["text"] == "一家人好"

    def test_中英文之间加空格_英文里的标点不动(self, toolkit) -> None:
        out = toolkit.clean_text({"text": "用Python写,Hello, world.", "space_between": "true"}, "zh")
        assert out["text"] == "用 Python 写，Hello, world."


class TestMarkdown转纯文本:
    def test_记号去掉_列表换圆点_代码块留代码(self, toolkit) -> None:
        md = "# 标题\n\n**加粗** 和 *斜体*,[链接](https://a.com),`code`,snake_case_name\n\n- 第一\n- [x] 第二\n> 引用\n\n```py\nprint(1)\n```\n---\n![图](x.png)"
        assert toolkit.strip_markdown({"text": md}, "zh")["text"] == (
            "标题\n\n加粗 和 斜体,链接,code,snake_case_name\n\n• 第一\n• 第二\n引用\n\nprint(1)\n\n图")

    def test_要网址就带在链接后面(self, toolkit) -> None:
        out = toolkit.strip_markdown({"text": "看[文档](https://mosael.com/docs)", "keep_urls": True}, "zh")
        assert out["text"] == "看文档 (https://mosael.com/docs)"

    def test_表格拆成一行一行(self, toolkit) -> None:
        assert toolkit.strip_markdown({"text": "| a | b |\n|---|:-:|\n| 1 | 2 |"}, "zh")["text"] == "a  b\n1  2"


class Test链接与提及:
    def test_网址邮箱提及各归各的_末尾标点不算(self, toolkit) -> None:
        text = "看 https://mosael.com/zh/docs. 和 www.example.com/a?b=1),联系 me@mosael.com 或 @小明 @Alice_W,见 medium.com/@bob"
        out = toolkit.extract_links({"text": text}, "zh")
        assert out["urls"] == ["https://mosael.com/zh/docs", "www.example.com/a?b=1"]
        assert out["emails"] == ["me@mosael.com"]
        assert out["mentions"] == ["小明", "Alice_W"]
        assert out["count"] == 5

    def test_重复的只留一次(self, toolkit) -> None:
        out = toolkit.extract_links({"text": "@a @A https://x.com https://x.com"}, "en")
        assert out["mentions"] == ["a"] and out["urls"] == ["https://x.com"]


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

    def test_工具集说明里不许诺没有的工具(self) -> None:
        skill = self.manifest()["toolsets"][0]["description"]
        #: 按整词找:「subtitle lines」(断成字幕行)不是在许诺起标题。
        assert "标题" not in skill["zh"] and not re.search(r"\btitles?\b", skill["en"], re.I)
