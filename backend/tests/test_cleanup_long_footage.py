"""口播整理在长素材上跑得下来:给模型的是段落级逐字稿,整理后的逐字稿在本地拼,删多了按置信度删到上限。

此前三处都会在长素材上失败:
- 提示词嵌整份词级逐字稿(每个词都带起止时间),20 分钟约 11 万字,超出多数模型的上下文;
- 方案的 schema 必填 cleaned_verbatim —— 模型要全文复述一遍,输出上限一到就截断,JSON 不闭合;
- 删除总时长超过上限就整步失败:多标了几处低置信度的停顿,一处都不删、后面的导出也没了。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from app.core.unit_of_work import unit_of_work
from app.db.models import Clip, Project, Sequence, Track, Workspace
from app.domain.workflows.executors.subjobs import _compact_timed_text, timeline_cut_ranges
from app.domain.workflows.templates_cleanup import _cleanup_schema
from tests.util import fresh_client, insert_asset


def _words(start: float, text: str, *, step: float = 0.25) -> list[dict]:
    return [{"start": round(start + index * step, 3), "end": round(start + index * step + 0.2, 3), "text": char}
            for index, char in enumerate(text)]


def test_二十分钟的逐字稿_只给段落和停顿附近的词() -> None:
    sentence = "今天我们来聊一聊怎么把一段口播剪得更紧凑一些"
    segments = []
    at = 0.0
    while at < 20 * 60:
        tokens = _words(at, sentence)
        segments.append({"start": at, "end": tokens[-1]["end"], "text": sentence, "speaker": "", "tokens": tokens})
        at = tokens[-1]["end"] + 0.3
    #: 一段里有一次 1.5 秒的停顿。
    paused = _words(at, "那个") + _words(at + 2.0, "我们继续")
    segments.append({"start": at, "end": paused[-1]["end"], "text": "那个我们继续", "speaker": "", "tokens": paused})

    encoded = _compact_timed_text(segments)
    words = sum(len(one["tokens"]) for one in segments)
    assert len(encoded) < words * 4, f"不再每个词都带时间:{len(encoded)} 字 / {words} 个词"

    rows = json.loads(encoded)["segments"]
    assert all("tokens" not in row and "pauses" not in row for row in rows[:-1]), "没有停顿的段只给起止和正文"
    last = rows[-1]
    assert last["pauses"] == [[paused[1]["end"], paused[2]["start"]]]
    assert [token[2] for token in last["tokens"]] == ["那", "个", "我", "们"], "停顿两边各两个词,口头禅就贴在那儿"


def test_方案不再要模型全文复述逐字稿() -> None:
    assert "cleaned_verbatim" not in _cleanup_schema()["properties"]


def _clip(seconds: float = 20.0) -> SimpleNamespace:
    fresh_client()
    with unit_of_work() as db:
        workspace = Workspace(name="W")
        db.add(workspace)
        db.flush()
        project = Project(workspace_id=workspace.id, name="P")
        db.add(project)
        db.commit()
        asset = insert_asset(workspace.id, kind="video", name="口播.mp4", media_info={"duration": seconds})
        sequence = Sequence(workspace_id=workspace.id, project_id=project.id, name="整理", width=320, height=240, fps=25)
        track = Track(sequence=sequence, kind="video", name="V1", position=0)
        db.add_all([sequence, track])
        db.flush()
        clip = Clip(workspace_id=workspace.id, sequence_id=sequence.id, track_id=track.id, asset_id=asset,
                    timeline_start=0, src_in=0, src_out=seconds)
        db.add(clip)
        db.commit()
        return SimpleNamespace(workspace=workspace.id, sequence=sequence.id, clip=clip.id)


def test_删多了按置信度删到上限_其余留给人复核_不再整步失败() -> None:
    ids = _clip(20.0)
    ranges = [
        {"src_start": 1.0, "src_end": 3.0, "confidence": 0.95, "reason": "长停顿"},
        {"src_start": 5.0, "src_end": 8.0, "confidence": 0.85, "reason": "重复"},
        {"src_start": 10.0, "src_end": 12.0, "confidence": 0.99, "reason": "错误起句"},
    ]
    scope = SimpleNamespace(workspace_id=ids.workspace, id="wf:1", name="整理")
    with unit_of_work() as db:
        out = timeline_cut_ranges(db, scope, {"sequence_id": ids.sequence, "clip_id": ids.clip, "ranges": ranges,
                                              "max_removal_ratio": 0.25})
    assert out["removed_seconds"] == 4.0, "上限 5 秒:先收 0.99、0.95 两处(4 秒),再加 3 秒就超了"
    assert [one["src_start"] for one in out["ranges"]] == [1.0, 10.0]
    assert [one["src_start"] for one in out["skipped_ranges"]] == [5.0]
    assert "1" in out["skipped_note"] and "25%" in out["skipped_note"]


def test_整理后的逐字稿按保留的原话在本地拼出来() -> None:
    ids = _clip(10.0)
    segments = [
        {"start": 0.0, "end": 1.2, "text": "大家好", "tokens": _words(0.0, "大家好", step=0.4)},
        {"start": 2.0, "end": 3.0, "text": "嗯嗯嗯", "tokens": []},
        {"start": 4.0, "end": 5.6, "text": "那个开始", "tokens": _words(4.0, "那个开始", step=0.4)},
    ]
    ranges = [{"src_start": 1.9, "src_end": 3.1, "confidence": 1}, {"src_start": 3.95, "src_end": 4.75, "confidence": 1}]
    scope = SimpleNamespace(workspace_id=ids.workspace, id="wf:1", name="整理")
    with unit_of_work() as db:
        out = timeline_cut_ranges(db, scope, {"sequence_id": ids.sequence, "clip_id": ids.clip, "ranges": ranges,
                                              "segments": segments})
    assert out["kept_text"] == "大家好\n开始", "整段删掉的不留;按词删的只去掉那几个字;一个字不改"
    assert out["skipped_note"] == ""


def test_中文段里夹着英文词_字之间不插空格_英文词之间照样空() -> None:
    """此前按整段判:中文段里只要有一个英文词,整段每个字之间都插了空格(「今 天 我 们 用 AI」)。"""
    ids = _clip(10.0)
    words = ["今", "天", "我", "们", "用", "AI", "做", "Hello", "world", ",", "OK", "嗯"]
    tokens = [{"text": word, "start": 0.2 * index, "end": 0.2 * index + 0.2} for index, word in enumerate(words)]
    segments = [{"start": 0.0, "end": 2.4, "text": "".join(words), "tokens": tokens}]
    #: 删掉最后那个「嗯」,这一段就按词拼回来。
    ranges = [{"src_start": 2.2, "src_end": 2.4, "confidence": 1}]
    scope = SimpleNamespace(workspace_id=ids.workspace, id="wf:1", name="整理")
    with unit_of_work() as db:
        out = timeline_cut_ranges(db, scope, {"sequence_id": ids.sequence, "clip_id": ids.clip, "ranges": ranges,
                                              "segments": segments})
    assert out["kept_text"] == "今天我们用AI做Hello world, OK"


def test_逐位给的数字拼回一个数_不在数字之间插空格() -> None:
    """SenseVoice 把「92」给成「9」「2」两个 token(实测)。此前两个数字之间也插了空格,整理后的逐字稿
    成了「水温控制在9 2度」「静置3 0秒」—— 这份逐字稿会进笔记、进通知。数字和英文词之间照样空一格。"""
    ids = _clip(10.0)
    words = ["水", "温", "9", "2", "度", "I", "have", "3", "0", "cats", "嗯"]
    tokens = [{"text": word, "start": 0.2 * index, "end": 0.2 * index + 0.2} for index, word in enumerate(words)]
    segments = [{"start": 0.0, "end": 2.2, "text": "".join(words), "tokens": tokens}]
    ranges = [{"src_start": 2.0, "src_end": 2.2, "confidence": 1}]
    scope = SimpleNamespace(workspace_id=ids.workspace, id="wf:1", name="整理")
    with unit_of_work() as db:
        out = timeline_cut_ranges(db, scope, {"sequence_id": ids.sequence, "clip_id": ids.clip, "ranges": ranges,
                                              "segments": segments})
    assert out["kept_text"] == "水温92度I have 30 cats"
