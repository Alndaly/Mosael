"""整条译配链路真的跑得起来:逐字稿 → 逐句翻译 → 字幕 → 变速配音 → 闪避。

**单个节点各自对,不等于这条链路对。** 这条工作流的价值全在几处交接上:译文的顺序要和段落
一一对上、时间码要来自原段落而不是译文、字幕的落点要加上视频接在第几秒、配音要按自己那一条
字幕的时长去变速。这几处都是"两个节点之间"的事,任何一个节点的单元测试都看不见。

所以这里跑的是**模板本身那张图**,经真的执行引擎。外部能力(识别、翻译、合成、渲染)换成
桩:它们各自有自己的测试,而且这条链路要验的从来不是"翻译翻得准不准"。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import Asset, Clip, Track, Transcript, TranscriptSegment, Workflow
from app.domain.jobs import create_job
from app.domain.workflows.engine import execute_graph
from app.domain.workflows.templates import translated_dub_graph
from tests.util import fresh_client

#: 两段日文,各 2 秒,中间空半秒。译文比原文长 —— 正是要靠变速压回去的那种情况。
SEGMENTS = [(0.0, 2.0, "こんにちは"), (2.5, 4.5, "元気ですか")]
TRANSLATED = {"こんにちは": "你好啊", "元気ですか": "你最近还好吗"}
#: 合成出来的音频都是 4 秒。段落只有 2 秒,所以每条都该被压成 2.0 倍速。
SYNTH_SECONDS = 4.0


@pytest.fixture
def stubs(monkeypatch):
    from app.domain import render, translate as translate_domain
    from app.domain.voices import transcription, voices

    def fake_transcribe(db, asset_id, *, created_by=None, language="", engine=""):
        asset = db.get(Asset, asset_id)
        transcript = Transcript(workspace_id=asset.workspace_id, asset_id=asset_id, language="ja")
        db.add(transcript)
        db.flush()
        for start, end, text in SEGMENTS:
            db.add(TranscriptSegment(
                transcript_id=transcript.id, start_time=start, end_time=end, text=text,
            ))
        job = create_job(db, workspace_id=asset.workspace_id, kind="transcribe",
                         payload={}, created_by=created_by)
        job.status = "succeeded"
        db.commit()
        return job

    def fake_translate(db, text, target_lang, *, user_id=None, engine="", profile_id=None):
        assert target_lang == "en", "模板的目标语言该原样传下去"
        return TRANSLATED.get(text, text)

    def fake_synthesis(db, *, text, project_id, created_by, **kwargs):
        sequence = db.scalars(select(Asset)).first()
        asset = Asset(
            workspace_id=sequence.workspace_id, kind="audio", source="tts",
            name=text[:20], media_info={"duration": SYNTH_SECONDS},
        )
        db.add(asset)
        db.flush()
        job = create_job(db, workspace_id=asset.workspace_id, kind="tts",
                         payload={}, created_by=created_by)
        job.status = "succeeded"
        job.result = {"asset_id": asset.id}
        db.commit()
        return job

    def fake_export(db, sequence_id, options=None, *, created_by=None):
        job = create_job(db, workspace_id=db.scalars(select(Asset)).first().workspace_id,
                         kind="render", payload={}, created_by=created_by)
        job.status = "succeeded"
        job.result = {"asset_id": "exported"}
        db.commit()
        return job

    monkeypatch.setattr(transcription, "start_transcription", fake_transcribe)
    monkeypatch.setattr(translate_domain, "translate", fake_translate)
    monkeypatch.setattr(voices, "start_synthesis", fake_synthesis)
    monkeypatch.setattr(render, "start_export", fake_export)


def _video_asset() -> tuple[str, str, str]:
    """一个工作区 + 一份 10 秒的视频素材 + 一条工作流。"""
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "译配"}).json()["id"]
    with SessionLocal() as db:
        asset = Asset(
            workspace_id=workspace, kind="video", source="import", name="讲话.mp4",
            media_info={"duration": 10.0, "width": 1920, "height": 1080, "fps": 30},
        )
        db.add(asset)
        workflow = Workflow(workspace_id=workspace, name="译配", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        return workspace, asset.id, workflow.id


def test_整条链路跑完之后时间线上该有什么(stubs) -> None:
    workspace, asset_id, workflow_id = _video_asset()
    graph = translated_dub_graph(voice_id="")
    for node in graph["nodes"]:
        if node["id"] == "source_video":
            node["config"]["asset_id"] = asset_id
        if node["id"] == "dubbing":
            # 引擎音色那条路:不需要配音库里有行,而两条路在这一步之后是同一条。
            node["config"].update(engine="volcano", engine_voice="voice-a", voice_id="")

    context, cancelled = execute_graph(graph, wf_id=workflow_id)
    assert not cancelled, context.get("__error__")

    sequence_id = context["dub_project"]["sequence_id"]
    with SessionLocal() as db:
        tracks = {
            track.id: track
            for track in db.scalars(select(Track).where(Track.sequence_id == sequence_id))
        }
        clips = list(db.scalars(select(Clip).where(Clip.sequence_id == sequence_id)))
        by_kind: dict[str, list[Clip]] = {}
        for clip in clips:
            by_kind.setdefault(tracks[clip.track_id].kind, []).append(clip)

        subtitles = sorted(by_kind["subtitle"], key=lambda c: c.timeline_start)
        assert [c.text_override for c in subtitles] == ["你好啊", "你最近还好吗"]
        # 时间码来自**原段落**,不是译文 —— 译文更长,跟着译文走的话从第一句就错位。
        assert [(c.timeline_start, c.src_out - c.src_in) for c in subtitles] == [(0.0, 2.0), (2.5, 2.0)]

        dub_track = next(t for t in tracks.values() if t.kind == "audio" and t.role == "dub")
        dubbed = sorted((c for c in by_kind["audio"] if c.track_id == dub_track.id),
                        key=lambda c: c.timeline_start)
        assert [c.timeline_start for c in dubbed] == [0.0, 2.5], "每条配音落在自己那条字幕的位置"
        # 4 秒的音频塞进 2 秒的段落 = 2 倍速。这就是"快进缩放到原音频段落长度"。
        assert [round(c.speed, 3) for c in dubbed] == [2.0, 2.0]

        # 原声不删,只闪避 —— 整条配音轨删掉就回到原样。
        original_audio = [t for t in tracks.values() if t.kind == "audio" and t.id != dub_track.id]
        assert original_audio and all(t.duck for t in original_audio)
        video_clips = by_kind["video"]
        assert len(video_clips) == 1 and video_clips[0].asset_id == asset_id

    assert context["dubbing"]["done"] == 2 and context["dubbing"]["failed"] == 0
    assert context["translated_subtitles"]["count"] == 2
