"""口播整理:口头禅不管在哪都带着时间交给模型,模型按时间删掉之后,时间线和整理后的逐字稿都对得上(标点照留)。

现场(上一轮实测):给模型的「紧凑逐字稿」只在长停顿附近给词级时间。连续说话被 VAD 切成一整段时,段里的「嗯」「就是说」
一个时间都没有,模型(k3)保守地一处都不删;整理后的逐字稿还把标点全丢了(按词拼回去,而 ASR 的词不带标点)。

最后一条**用官方模板真建图、真跑引擎**:降噪、转写换成假的(转写给一整段没有停顿的口播,夹着口头禅),大模型用替身 ——
它只能从发给它的提示词里读口头禅的时间,按读到的时间出删除范围。逐个节点看过程:发给模型的输入里每个口头禅都带时间、
正文带标点;时间线上真的切掉了那几段;整理后的逐字稿是原话去掉口头禅、标点照留。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from app.core import http_retry
from app.core.db import SessionLocal
from app.db.models import Asset, Clip, Transcript, TranscriptSegment, TranscriptToken
from app.domain.workflows.executors.subjobs import _compact_timed_text, _kept_text
from tests.util import add_provider, fresh_client, wait_status

#: 一整段连续的口播(没有一处 ≥0.6 秒的停顿),夹着三处口头禅;标点只在正文里,词级 token 不带标点。
TEXT = "大家好,嗯,今天我们就是说来聊一聊剪辑。然后呃这个工具真的很好用。"
CLEANED = "大家好,今天我们来聊一聊剪辑。然后这个工具真的很好用。"
STEP = 0.2


def _tokens(text: str) -> list[dict]:
    """逐字的 token(SenseVoice / Paraformer 的中文就是这样),一个接一个、中间没有空隙;标点不成 token。"""
    chars = [char for char in text if char not in ",。"]
    return [{"start": round(index * STEP, 3), "end": round(index * STEP + STEP, 3), "text": char} for index, char in enumerate(chars)]


TOKENS = _tokens(TEXT)
#: 三处口头禅按 token 的位置:「嗯」第 3 个、「就是说」第 8–10 个、「呃」第 19 个。
FILLERS = [[0.6, 0.8, "嗯"], [1.6, 2.2, "就是说"], [3.8, 4.0, "呃"]]
DURATION = round(len(TOKENS) * STEP + 0.2, 3)


def test_连续一整段里的口头禅_不在停顿附近也带着时间_正文带标点() -> None:
    segment = {"start": 0.0, "end": TOKENS[-1]["end"], "text": TEXT, "speaker": "", "tokens": TOKENS}
    encoded = json.loads(_compact_timed_text([segment]))
    (row,) = encoded["segments"]
    assert row["text"] == TEXT, "正文照原样给,标点在"
    assert "pauses" not in row and "tokens" not in row, "这一段没有停顿"
    assert row["fillers"] == FILLERS, "每个口头禅都带起止 —— 连成几个 token 的「就是说」是一项"
    assert encoded["token_columns"] == ["start", "end", "text"]


def test_英文的口头禅和歧义词也是候选_交给模型看上下文() -> None:
    words = ["So", "um", "I", "like", "this", "uh", "a", "lot"]
    tokens = [{"start": round(index * 0.3, 3), "end": round(index * 0.3 + 0.3, 3), "text": word} for index, word in enumerate(words)]
    segment = {"start": 0.0, "end": 2.4, "text": "So, um, I like this, uh, a lot.", "tokens": tokens}
    (row,) = json.loads(_compact_timed_text([segment]))["segments"]
    assert row["fillers"] == [[0.3, 0.6, "um"], [0.9, 1.2, "like"], [1.5, 1.8, "uh"]]


@pytest.mark.parametrize(("text", "words", "removed", "expected"), [
    #: 口头禅后面的逗号跟着它一起走;前面那个保留的词后面有标点就留那个。
    ("大家好,嗯,今天", list("大家好嗯今天"), [(0.6, 0.8)], "大家好,今天"),
    #: 前一个词后面没有标点、被删的那串后面只有逗号:逗号不留(它是给口头禅停顿的)。
    ("我觉得嗯,这个", list("我觉得嗯这个"), [(0.6, 0.8)], "我觉得这个"),
    #: 删到句末:句号留着。
    ("今天很好嗯。", list("今天很好嗯"), [(0.8, 1.0)], "今天很好。"),
    #: 删在段首:后面的逗号不留。
    ("嗯,开始吧。", list("嗯开始吧"), [(0.0, 0.2)], "开始吧。"),
    #: 英文:空格和逗号照原文。
    ("So, um, we start.", ["So", "um", "we", "start"], [(0.2, 0.4)], "So, we start."),
])
def test_按词删过的段_标点照原文留(text: str, words: list[str], removed: list, expected: str) -> None:
    tokens = [{"start": round(index * 0.2, 3), "end": round(index * 0.2 + 0.2, 3), "text": word} for index, word in enumerate(words)]
    segment = {"start": 0.0, "end": tokens[-1]["end"], "text": text, "tokens": tokens}
    assert _kept_text([segment], removed) == expected


def test_token_对不回正文时_照旧按词拼() -> None:
    """引擎的正文和 token 写法不一样(一个写「92」、一个按读音给「九十二」):对不回去就按词拼,不瞎对。"""
    tokens = [{"start": 0.0, "end": 0.2, "text": "水"}, {"start": 0.2, "end": 0.4, "text": "九"}, {"start": 0.4, "end": 0.6, "text": "十"},
              {"start": 0.6, "end": 0.8, "text": "二"}, {"start": 0.8, "end": 1.0, "text": "嗯"}]
    segment = {"start": 0.0, "end": 1.0, "text": "水92,嗯", "tokens": tokens}
    assert _kept_text([segment], [(0.8, 1.0)]) == "水九十二"


# ---- 官方模板真跑一遍 ----


@pytest.fixture
def studio(monkeypatch):
    """一个工作区、一份视频、一条大模型连接;降噪 / 转写 / 导出换成桩,大模型换成替身(MockTransport)。"""
    from app.domain import render
    from app.domain.assets import denoise
    from app.domain.jobs import create_job
    from app.domain.voices import transcription

    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(key, raising=False)
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        video = Asset(workspace_id=ws, kind="video", source="import", name="口播.mp4",
                      media_info={"duration": DURATION, "width": 1920, "height": 1080, "fps": 30})
        profile = add_provider(db, name="模型", vendor="openai-compatible", base_url="https://llm.test/v1",
                               api_key="sk-test", model="writer")
        db.add(video)
        db.commit()
        ids = SimpleNamespace(client=client, ws=ws, video=video.id, profile=profile.id)

    def fake_denoise(db, *, asset, created_by=None, engine="", strength=""):
        job = create_job(db, workspace_id=asset.workspace_id, kind="denoise", payload={}, created_by=created_by)
        job.status, job.result = "succeeded", {"asset_id": asset.id, "engine": "builtin:rnnoise"}
        db.commit()
        return job

    def fake_transcribe(db, asset_id, *, created_by=None, language="", engine=""):
        transcript = Transcript(workspace_id=ids.ws, asset_id=asset_id, language="zh", source="test")
        segment = TranscriptSegment(transcript=transcript, start_time=0.0, end_time=TOKENS[-1]["end"], text=TEXT)
        segment.tokens = [TranscriptToken(token_index=index, start_time=one["start"], end_time=one["end"], text=one["text"])
                          for index, one in enumerate(TOKENS)]
        db.add_all([transcript, segment])
        db.flush()
        job = create_job(db, workspace_id=ids.ws, kind="transcribe", payload={}, created_by=created_by)
        job.status, job.result = "succeeded", {"transcript_id": transcript.id}
        db.commit()
        return job

    def fake_export(db, sequence_id, params=None, *, created_by=None):
        job = create_job(db, workspace_id=ids.ws, kind="render", payload={"sequence_id": sequence_id}, created_by=created_by)
        job.status, job.result = "succeeded", {"asset_id": ids.video}
        db.commit()
        return job

    monkeypatch.setattr(denoise, "start_denoise_job", fake_denoise)
    monkeypatch.setattr(transcription, "start_transcription", fake_transcribe)
    monkeypatch.setattr(render, "start_export", fake_export)

    #: 大模型替身:只能从发给它的提示词里读口头禅的时间,按读到的时间出删除范围 —— 读不到就一处都不删(和 k3 一样保守)。
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        prompt = body["messages"][1]["content"]
        start = prompt.index('{"token_columns"')
        transcript, _ = json.JSONDecoder().raw_decode(prompt[start:])
        ranges = [
            {"src_start": begin, "src_end": end, "issue_type": "filler", "reason": f"口头禅「{word}」",
             "transcript_excerpt": word, "confidence": 0.95}
            for row in transcript["segments"] for begin, end, word in row.get("fillers", [])
        ]
        plan = {"editorial_summary": "去掉口头禅", "revised_outline": [], "issues": [], "remove_ranges": ranges,
                "review_notes": [], "estimated_removed_seconds": round(sum(one["src_end"] - one["src_start"] for one in ranges), 3)}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(plan, ensure_ascii=False)}}],
                                         "usage": {"prompt_tokens": 10, "completion_tokens": 10}})

    real = http_retry.RetryingClient
    monkeypatch.setattr(http_retry, "RetryingClient",
                        lambda *a, **k: real(*a, **{**k, "transport": httpx.MockTransport(handler)}))
    monkeypatch.setattr(http_retry.time, "sleep", lambda *a, **k: None)
    ids.llm_requests = seen
    return ids


def test_官方模板真跑_模型拿到口头禅的时间_按时间删掉_时间线和整理后的逐字稿对得上(studio) -> None:
    from app.domain.workflows.templates import localised_names, transcript_video_cleanup_graph
    from app.domain.workflows.templates_models import ModelChoice

    chat = ModelChoice(profile_id=studio.profile, provider="openai-compatible", model="writer")
    graph = localised_names("zh", transcript_video_cleanup_graph(chat=chat, locale="zh"))
    next(node for node in graph["nodes"] if node["id"] == "source_video")["config"]["asset_id"] = studio.video
    #: 和用户一样:存下这张图、点运行(运行前检查、任务线程、引擎都是真的)。
    saved = studio.client.post("/api/workflows", json={"workspace_id": studio.ws, "name": "口播整理", "graph": graph})
    assert saved.status_code == 200, saved.text
    run = studio.client.post(f"/api/workflows/{saved.json()['id']}/run", json={"params": {}})
    assert run.status_code == 200, run.text
    assert wait_status(studio.client, run.json()["id"], timeout=60) == "succeeded", \
        studio.client.get(f"/api/jobs/{run.json()['id']}").json().get("error")
    context = studio.client.get(f"/api/jobs/{run.json()['id']}").json()["result"]["context"]

    #: 转写节点交出去的紧凑逐字稿:口头禅都带时间,正文带标点。
    timed = json.loads(context["verbatim_transcript"]["timed_text"])
    assert timed["segments"][0]["fillers"] == FILLERS and timed["segments"][0]["text"] == TEXT

    #: 发给模型的提示词里就是这一份(引用解析之后原样嵌进去),系统提示说了口头禅按 fillers 的时间切。
    (request,) = studio.llm_requests
    assert context["verbatim_transcript"]["timed_text"] in request["messages"][1]["content"]
    assert "fillers" in request["messages"][0]["content"]

    #: 模型按读到的时间出了三处删除范围,裁切节点照单全收。
    applied = [(one["src_start"], one["src_end"]) for one in context["apply_cleanup"]["ranges"]]
    assert applied == [(0.6, 0.8), (1.6, 2.2), (3.8, 4.0)]
    assert context["apply_cleanup"]["removed_seconds"] == pytest.approx(1.0)
    assert context["apply_cleanup"]["skipped_ranges"] == []

    #: 时间线上真的切掉了那三段:留下的片段首尾相接,源区间正好绕开口头禅。
    with SessionLocal() as db:
        clips = sorted(db.query(Clip).filter(Clip.sequence_id == context["cleanup_project"]["sequence_id"]).all(),
                       key=lambda clip: clip.timeline_start)
        spans = [(round(clip.src_in, 3), round(clip.src_out, 3)) for clip in clips]
        starts = [round(clip.timeline_start, 3) for clip in clips]
    assert spans == [(0.0, 0.6), (0.8, 1.6), (2.2, 3.8), (4.0, DURATION)]
    assert starts == [0.0, 0.6, 1.4, 3.0]

    #: 整理后的逐字稿:原话去掉三处口头禅,标点照留;交付里的那一份就是它。
    assert context["apply_cleanup"]["kept_text"] == CLEANED
    assert context["output"]["output"]["cleaned_verbatim"] == CLEANED
