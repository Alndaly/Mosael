"""补上的几个工具:模型**够不着**的那几件事。

这些不是锦上添花,每一条都对应一件模型此前只能猜或只能放弃的事:

- 「今天几号」——训练有截止日期,而按日期命名、筛「最近的素材」、写文案里的日期都要它。
- 「渲染好了吗」——只有 get_job(要 id),没有列表,模型拿不到 id 就无从查起。
- 「这段视频说了什么」——能发起转写(transcribe_asset),却读不到结果,于是
  按内容剪辑、总结、找一句话全部做不到。
- 「在哪个工作区」——每个工具的 workspace_id 都默认回落到第一个,而这个回落是**看不见的**。
- 「把这个链接下下来」——从链接导入是 0.18 加的能力,只在界面上有。
"""
from __future__ import annotations

import asyncio

import mcp_server
from tests.util import fresh_client

#: 这次补的工具,以及它各自补上的那个缺口(写在这里,是为了下次有人想删时先读到理由)。
ADDED = {
    "get_current_time": "模型没有别的办法知道今天是几号",
    "list_jobs": "get_job 要 id,而用户问「好了吗」时没人有 id",
    "get_transcript": "能发起转写却读不到结果,按内容剪辑因此做不到",
    "list_workspaces": "workspace_id 的默认回落是看不见的",
    "import_media_from_url": "从链接导入只在界面上有",
}


def test_the_added_tools_reach_the_agent() -> None:
    """光有函数不算数 —— 要出现在智能体拿到的那份清单里。"""
    names = {tool.name for tool in asyncio.run(mcp_server.mcp.list_tools())}
    missing = sorted(name for name in ADDED if name not in names)
    assert missing == [], f"这些工具没进清单:{missing}"


def test_they_are_in_the_manifest_the_runtime_reads() -> None:
    with fresh_client() as client:
        served = {tool["name"] for tool in client.get("/api/agent/tools").json()}
    missing = sorted(name for name in ADDED if name not in served)
    assert missing == [], f"这些工具没被 /api/agent/tools 端出去:{missing}"


def test_every_added_tool_says_when_to_use_it() -> None:
    """描述得说清「什么时候用」。模型选错工具的代价是它去凑一个 —— 而它不会说自己没有。"""
    by_name = {tool.name: tool for tool in asyncio.run(mcp_server.mcp.list_tools())}
    for name in ADDED:
        text = by_name[name].description or ""
        assert "Use " in text or "use " in text, f"{name} 的描述没说什么时候该用它"


def test_current_time_is_real_and_admits_an_unknown_zone() -> None:
    now = mcp_server.get_current_time()
    assert now["date"] == now["local"][:10]
    assert now["utc"].endswith("+00:00")
    assert now["unix"] > 1_700_000_000
    assert "warning" not in now

    tokyo = mcp_server.get_current_time("Asia/Tokyo")
    assert tokyo["timezone"] == "Asia/Tokyo"
    assert tokyo["utc_offset"] == "+09:00"
    assert tokyo["unix"] == now["unix"] or abs(tokyo["unix"] - now["unix"]) <= 2

    # 认不出的时区**不能悄悄按本机算**:那会让「按东京时间」静静地算错,而结果看着完全正常。
    bad = mcp_server.get_current_time("Mars/Olympus")
    assert "warning" in bad and "Mars/Olympus" in bad["warning"]


def test_transcript_narrows_by_time_and_owns_up_to_truncating(monkeypatch) -> None:
    """截断必须说出来 —— 「就这些了」和「还有很多」在模型眼里否则一模一样。"""
    segments = [
        {"start_time": i * 2.0, "end_time": i * 2.0 + 1.5, "text": f"第{i}句", "speaker": "A", "tokens": [1, 2, 3]}
        for i in range(500)
    ]
    monkeypatch.setattr(mcp_server, "_get", lambda path, params=None: {
        "language": "zh", "status": "done", "segments": segments,
    })

    whole = mcp_server.get_transcript("a1")
    assert whole["total_segments"] == 500
    assert whole["truncated"] is True
    assert len(whole["segments"]) == 200
    # 逐词 token 不该回去 —— 剪辑要的是段落时间,而 token 会把上下文吃干。
    assert "tokens" not in whole["segments"][0]
    assert whole["text"].startswith("第0句 第1句")

    window = mcp_server.get_transcript("a1", start_seconds=10, end_seconds=20)
    assert window["truncated"] is False
    assert all(seg["end_time"] > 10 and seg["start_time"] < 20 for seg in window["segments"])
    assert window["total_segments"] == len(window["segments"])


def test_transcript_keeps_the_speaker_only_when_there_is_one(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "_get", lambda path, params=None: {
        "language": "zh", "status": "done",
        "segments": [
            {"start_time": 0, "end_time": 1, "text": "有说话人", "speaker": "B"},
            {"start_time": 1, "end_time": 2, "text": "没有", "speaker": None},
        ],
    })
    segs = mcp_server.get_transcript("a1")["segments"]
    assert segs[0]["speaker"] == "B"
    assert "speaker" not in segs[1], "没有说话人时不该塞一个空的 —— 那会读成「有个叫 None 的人」"


def test_url_import_refuses_a_link_it_could_not_probe(monkeypatch) -> None:
    """探不到条目就别硬下:那多半是链接不对,而「下了个空」比报错更难查。"""
    import pytest

    monkeypatch.setattr(mcp_server, "_default_workspace_id", lambda: "w1")
    monkeypatch.setattr(mcp_server, "_post", lambda path, body=None: {"title": "", "entries": []})
    with pytest.raises(ValueError, match="探不到"):
        mcp_server.import_media_from_url("https://example.com/nope")


def test_url_import_only_takes_video_or_audio(monkeypatch) -> None:
    import pytest

    with pytest.raises(ValueError, match="video"):
        mcp_server.import_media_from_url("https://example.com/x", kind="subtitles")
