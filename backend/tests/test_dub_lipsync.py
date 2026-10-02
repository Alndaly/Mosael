"""译配对口型(ADR 0028 阶段 3「视频翻译 · 改口型」)。

- 切块:每块在模型收得下的长度里,切点优先落在两句之间;没有空当才在上限处硬切;最后一块太短就把上一个切点往前挪;
- 有配音的块交给改口型,一句都没有的块用原片、不花钱;接回整段不带声音,放到最上面一条新视频轨,原片不动;
- 授权没确认、原片变过速、配音轨上没有话,都在动手之前说;
- 等改口型时调用方的会话被交还(commit + close):之后铺时间线不能再碰脱离会话的对象 —— 桩走真的 wait_for_job;
- 配音轨上的克隆音色、原片上的真人人物,在花钱之前按漏斗同一套判据查;
- 失败重跑不再买已经改好的块;中间素材挂在译配项目下;起点在原片之前的那句台词不往后错。
"""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from app.core.unit_of_work import unit_of_work
from app.core.config import settings
from app.db.models import Asset, Clip, Entity, EntityReference, Job, Project, Sequence, Track, Voice, Workspace
from app.domain.assets.importer import register_file_asset
from app.domain.render import build_plan_for_sequence, digital_human_assets
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.executors import dub_lipsync as module
from app.domain.workflows.executors.dub_lipsync import dub_lipsync, plan_chunks
from tests.util import fresh_client, make_voice


def test_切块_切点落在两句之间_没空当才硬切_最后一块太短往前挪() -> None:
    assert plan_chunks(50, [(1, 10)], 2, 120) == [(0.0, 50)]
    lines = [(0, 50), (60, 110), (130, 200)]
    assert plan_chunks(200, lines, 2, 120) == [(0.0, 120.0), (120.0, 200)], "55 和 120 都是空当,取不超上限的最远那个"
    assert plan_chunks(250, [(0, 250)], 2, 120) == [(0.0, 120.0), (120.0, 240.0), (240.0, 250)], "一直在说话:上限处硬切"
    assert plan_chunks(241, [(0, 241)], 2, 120) == [(0.0, 120.0), (120.0, 239), (239, 241)], "最后一块 1 秒不收:切点往前挪"


def _media(key: str, args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args, str(settings.data_dir / key)], check=True)


@pytest.fixture()
def dubbed(monkeypatch):
    """一条 6 秒原片 + 一条配音轨(第 1 秒、第 4 秒各一句,每句 1 秒)。改口型换成「交回那一块原片」。"""
    fresh_client()
    _media("src.mp4", ["-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=6", "-f", "lavfi", "-i",
                       "sine=duration=6", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p"])
    _media("line.wav", ["-f", "lavfi", "-i", "sine=frequency=660:duration=1"])
    with unit_of_work() as db:
        ws = Workspace(name="W")
        db.add(ws)
        db.flush()
        project = Project(workspace_id=ws.id, name="P")
        db.add(project)
        db.flush()
        video = register_file_asset(db, workspace_id=ws.id, project_id=None, source_path=settings.data_dir / "src.mp4", name="原片")
        line = register_file_asset(db, workspace_id=ws.id, project_id=None, source_path=settings.data_dir / "line.wav", name="一句")
        sequence = Sequence(workspace_id=ws.id, project_id=project.id, name="译配版", width=320, height=240, fps=25)
        base = Track(sequence=sequence, kind="video", name="V1", position=0)
        dub = Track(sequence=sequence, kind="audio", name="A1", position=1)
        db.add_all([sequence, base, dub])
        db.flush()
        source = Clip(workspace_id=ws.id, sequence_id=sequence.id, track_id=base.id, asset_id=video.id,
                      timeline_start=0, src_in=0, src_out=6)
        db.add(source)
        for at in (1, 4):
            db.add(Clip(workspace_id=ws.id, sequence_id=sequence.id, track_id=dub.id, asset_id=line.id,
                        timeline_start=at, src_in=0, src_out=1))
        db.commit()
        ids = SimpleNamespace(ws=ws.id, sequence=sequence.id, clip=source.id, dub=dub.id, base=base.id,
                              project=project.id, video=video.id, line=line.id)
    calls: list = []
    model = {"id": "p:video:videoretalk", "provider": "p", "provider_profile_id": "p", "model": "videoretalk",
             "capabilities": {"source_duration_seconds": {"source_video": [2, 4]}}}
    monkeypatch.setattr(module, "_pick_model", lambda db, choice, mode: model)

    def generation(db, **request):
        """改口型的供应商:建一条已经成功的子任务,产出就是那一块原片。**不绕过 _generate** —— 它照常提交、
        起线程(这里什么都不做)、走真的 wait_for_job 把调用方的会话交还(commit + close)。"""
        calls.append(request)
        job = Job(workspace_id=request["workspace_id"], kind="generation", status="succeeded", created_by=None,
                  result={"asset_ids": [request["source_assets"][0]["asset_id"]]})
        db.add(job)
        db.flush()
        return SimpleNamespace(id=job.id), job

    monkeypatch.setattr("app.domain.generation.create_generation_job", generation)
    monkeypatch.setattr("app.domain.generation.runner.start_generation_thread", lambda generation_id: None)
    return ids, calls


def _config(ids, **extra):
    return {"sequence_id": ids.sequence, "clip_id": ids.clip, "track_id": ids.dub, "consent": "yes", **extra}


def test_整条跑通_切两块都改口型_接回整段放在最上面_原片不动(dubbed) -> None:
    ids, calls = dubbed
    scope = SimpleNamespace(workspace_id=ids.ws, id="wf:1", name="译配")
    with unit_of_work() as db:
        out = dub_lipsync(db, scope, _config(ids))
    assert (out["chunk_count"], out["generated_count"]) == (2, 2), "6 秒按 4 秒上限、在两句之间(第 3 秒)切成两块"
    assert [[one["role"] for one in call["source_assets"]] for call in calls] == [["source_video", "driving_audio"]] * 2
    with unit_of_work() as db:
        sequence = db.get(Sequence, ids.sequence)
        top = min(sequence.tracks, key=lambda track: track.position)
        assert top.id == out["track_id"] and top.kind == "video", "新轨挪到最上面,盖住原片"
        placed = db.get(Clip, out["clip_id"])
        assert placed.track_id == top.id and placed.timeline_start == 0 and abs(placed.src_out - 6) < 0.2
        assert db.get(Clip, ids.clip).track_id == ids.base, "原片不动"
        final = settings.data_dir / placed.asset.file_key
        assert digital_human_assets(db, {placed.asset_id}) == {placed.asset_id}, "接回的整段不是生成记录的产出,也认得出是数字人"
        # 出处:切出来的每块原片 ← 原片(截取),每块配音 ← 配音轨上那几句(混音),接回的整段 ← 原片 + 改好的每一块。
        pieces = [call["source_assets"][0]["asset_id"] for call in calls]
        assert placed.asset.derived_from == [{"asset_id": ids.video, "op": "concat"}] + [
            {"asset_id": one, "op": "concat"} for one in pieces]
        assert placed.asset.ai_generated is True
        for call in calls:
            piece, speech = (db.get(Asset, one["asset_id"]) for one in call["source_assets"])
            assert piece.derived_from == [{"asset_id": ids.video, "op": "trim"}]
            assert speech.derived_from == [{"asset_id": ids.line, "op": "mix"}]
        plan = build_plan_for_sequence(db, ids.sequence, {})
        assert "AIGC" in dict(plan.output.metadata) and plan.text_overlays, "导出这条时间线:画面标识、AIGC 元数据都加上"
    streams = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(final)],
                                        capture_output=True, text=True, check=True).stdout)["streams"]
    assert [one["codec_type"] for one in streams] == ["video"], "声音在配音轨和背景轨上,接回的整段不带声音"


def test_没有配音的块用原片_不花钱(dubbed) -> None:
    ids, calls = dubbed
    with unit_of_work() as db:
        for clip in db.query(Clip).filter(Clip.track_id == ids.dub, Clip.timeline_start == 4):
            db.delete(clip)
        db.commit()
    scope = SimpleNamespace(workspace_id=ids.ws, id="wf:1", name="译配")
    with unit_of_work() as db:
        out = dub_lipsync(db, scope, _config(ids))
    assert (out["chunk_count"], out["generated_count"], len(calls)) == (2, 1, 1)


def test_动手之前说清楚(dubbed) -> None:
    ids, calls = dubbed
    scope = SimpleNamespace(workspace_id=ids.ws, id="wf:1", name="译配")
    with unit_of_work() as db:
        with pytest.raises(WorkflowDomainError) as refused:
            dub_lipsync(db, scope, _config(ids, consent=""))
        assert refused.value.key == "wfErr_talkingNeedsConsent"
        db.get(Clip, ids.clip).speed = 1.5
        db.commit()
        with pytest.raises(WorkflowDomainError) as refused:
            dub_lipsync(db, scope, _config(ids))
        assert refused.value.key == "wfErr_dubLipsyncSpeed"
        db.get(Clip, ids.clip).speed = 1.0
        for clip in db.query(Clip).filter(Clip.track_id == ids.dub):
            db.delete(clip)
        db.commit()
        with pytest.raises(WorkflowDomainError) as refused:
            dub_lipsync(db, scope, _config(ids))
        assert refused.value.key == "wfErr_dubLipsyncNoSpeech"
    assert calls == []


def _run(ids, **extra):
    scope = SimpleNamespace(workspace_id=ids.ws, id="wf:1", name="译配")
    with unit_of_work() as db:
        return dub_lipsync(db, scope, _config(ids, **extra))


def test_等改口型时会话被交还_之后照样铺上时间线_中间素材挂在译配项目下(dubbed) -> None:
    """此前付完钱、改好口型,在读 `sequence.tracks`(之前没加载过)那一行 DetachedInstanceError —— 旧的桩直接
    返回结果、不交还会话,把它盖住了。"""
    ids, calls = dubbed
    out = _run(ids)
    assert out["generated_count"] == 2 and len(calls) == 2
    assert {call["project_id"] for call in calls} == {ids.project}, "改口型的产出挂在译配项目下"
    with unit_of_work() as db:
        made = [one for one in db.query(Asset).filter(Asset.workspace_id == ids.ws) if one.id not in (ids.video, ids.line)]
        assert made and {one.project_id for one in made} == {ids.project}, "切出来的块、接回的整段都不散落在「未归属」里"
        assert db.get(Clip, out["clip_id"]).track_id == out["track_id"]


def test_失败重跑不再买已经改好的块(dubbed) -> None:
    ids, calls = dubbed
    _run(ids)
    assert len(calls) == 2
    again = _run(ids)
    assert (again["generated_count"], again["reused_count"], len(calls)) == (0, 2, 2), "原片、区间、配音、模型都一样:认出来,不再花钱"

    #: 第二句换成另一段音频(字幕配音配出来的、念的是另一句话),那一块就是新的:切点不变,只重买变了的那一块。
    #: 认句子按配音记在音频上的那句话和那把嗓子,不按字节(整图重跑时见 test_dub_lipsync_rerun_cache)。
    _media("other.wav", ["-f", "lavfi", "-i", "sine=frequency=440:duration=1"])
    with unit_of_work() as db:
        other = register_file_asset(db, workspace_id=ids.ws, project_id=None, source_path=settings.data_dir / "other.wav",
                                    name="另一句")
        other.media_info = {**other.media_info, "dub_line": {"text": "另一句话", "voice": "engine=builtin:volcano"}}
        changed = db.query(Clip).filter(Clip.track_id == ids.dub, Clip.timeline_start == 4).one()
        changed.asset_id = other.id
        db.commit()
    third = _run(ids)
    assert (third["generated_count"], third["reused_count"], len(calls)) == (1, 1, 3)

    #: 只调音量不改说的话:嘴型不变,不重买。
    with unit_of_work() as db:
        db.query(Clip).filter(Clip.track_id == ids.dub, Clip.timeline_start == 4).one().gain = 0.5
        db.commit()
    fourth = _run(ids)
    assert (fourth["generated_count"], len(calls)) == (0, 3)


def test_配音轨上是未声明的克隆音色_花钱之前就拒(dubbed) -> None:
    """配音混成一段新 wav 交给改口型,新素材上不记 voice_id —— 漏斗查不到;得拿配音轨上原来那几句查。"""
    ids, calls = dubbed
    voice = make_voice(ids.ws, "老王的嗓子")
    with unit_of_work() as db:
        line = db.get(Asset, ids.line)
        line.media_info = {**(line.media_info or {}), "voice_id": voice}
        db.commit()
    with pytest.raises(WorkflowDomainError) as refused:
        _run(ids)
    assert refused.value.key == "genErr_voiceConsentMissing" and calls == []
    with unit_of_work() as db:
        db.get(Voice, voice).consent_kind = "self"
        db.commit()
    assert _run(ids)["generated_count"] == 2


def test_原片是真人人物资产的参考图_没有声明就拒(dubbed) -> None:
    ids, calls = dubbed
    with unit_of_work() as db:
        person = Entity(workspace_id=ids.ws, kind="character", name="小李", attributes={"real_person": True})
        db.add(person)
        db.flush()
        db.add(EntityReference(entity_id=person.id, asset_id=ids.video, role="front"))
        db.commit()
    with pytest.raises(WorkflowDomainError) as refused:
        _run(ids)
    assert refused.value.key == "genErr_entityConsentMissing" and calls == []


def test_起点在原片之前的那句_剪掉露在外面的那截_不往后错(monkeypatch) -> None:
    """配音轨上一句从原片开始前 0.5 秒说起:混音时它应当从这句露在里面的那一截念起、落在 0 秒。此前起点夹到 0,
    截取却仍从这句的开头算 —— 整句往后错了 0.5 秒。"""
    import app.domain.workflows.executors.subjobs as subjobs

    monkeypatch.setattr(subjobs, "_asset_in", lambda db, scope, asset_id: SimpleNamespace(id=asset_id, file_key="k", media_info={}))
    early = SimpleNamespace(muted=False, asset_id="a", timeline_start=9.5, src_in=0.0, src_out=2.0, speed=2.0, gain=1.0)
    [line] = module._lines_on(None, SimpleNamespace(workspace_id="w"), SimpleNamespace(clips=[early]),
                              clip_start=10.0, span=6.0)
    assert (line.start, line.end) == (0.0, 0.5), "2 倍速:素材 2 秒 = 时间线 1 秒,其中前 0.5 秒露在原片之前"
    assert line.src_in == pytest.approx(1.0), "时间线上剪掉 0.5 秒 = 素材里 1 秒(2 倍速)"


@pytest.mark.parametrize("rate", ["30000/1001", "24000/1001"])
def test_帧率不是整数的原片_切出来的每块都在模型收的长度里(monkeypatch, rate) -> None:
    """切块要重新编码,时长按帧取整:29.97 fps 下正好在上限处硬切,出来比上限多 0.02 秒,漏斗按「超过上限」拒掉。
    走真的切块和 ffmpeg,改口型的桩里用漏斗**同一个**时长判据(generation.operations._check_source_duration)查每一块。"""
    from app.domain.generation import operations

    fresh_client()
    _media("ntsc.mp4", ["-f", "lavfi", "-i", f"testsrc=size=160x120:rate={rate}:duration=25", "-c:v", "libx264",
                        "-preset", "ultrafast", "-pix_fmt", "yuv420p"])
    _media("talk.wav", ["-f", "lavfi", "-i", "sine=frequency=500:duration=25"])
    with unit_of_work() as db:
        ws = Workspace(name="W")
        db.add(ws)
        db.flush()
        video = register_file_asset(db, workspace_id=ws.id, project_id=None, source_path=settings.data_dir / "ntsc.mp4", name="原片")
        talk = register_file_asset(db, workspace_id=ws.id, project_id=None, source_path=settings.data_dir / "talk.wav", name="一直在说")
        project = Project(workspace_id=ws.id, name="P")
        db.add(project)
        db.flush()
        sequence = Sequence(workspace_id=ws.id, project_id=project.id, name="译配版", width=160, height=120, fps=30)
        base = Track(sequence=sequence, kind="video", name="V1", position=0)
        dub = Track(sequence=sequence, kind="audio", name="A1", position=1)
        db.add_all([sequence, base, dub])
        db.flush()
        span = float(video.media_info["duration"])
        source = Clip(workspace_id=ws.id, sequence_id=sequence.id, track_id=base.id, asset_id=video.id,
                      timeline_start=0, src_in=0, src_out=span)
        #: 从头说到尾,没有空当可切:只能在上限处硬切 —— 正是按帧取整会冒出上限的那种切法。
        db.add_all([source, Clip(workspace_id=ws.id, sequence_id=sequence.id, track_id=dub.id, asset_id=talk.id,
                                 timeline_start=0, src_in=0, src_out=span)])
        db.commit()
        ids = SimpleNamespace(ws=ws.id, sequence=sequence.id, clip=source.id, dub=dub.id)
    limits = [2, 10]
    model = {"id": "p:video:videoretalk", "provider": "p", "provider_profile_id": "p", "model": "videoretalk",
             "capabilities": {"source_duration_seconds": {"source_video": limits}}}
    monkeypatch.setattr(module, "_pick_model", lambda db, choice, mode: model)

    def generation(db, **request):
        piece = db.get(Asset, request["source_assets"][0]["asset_id"])
        operations._check_source_duration(piece, "source_video", limits)
        job = Job(workspace_id=request["workspace_id"], kind="generation", status="succeeded", created_by=None,
                  result={"asset_ids": [piece.id]})
        db.add(job)
        db.flush()
        return SimpleNamespace(id=job.id), job

    monkeypatch.setattr("app.domain.generation.create_generation_job", generation)
    monkeypatch.setattr("app.domain.generation.runner.start_generation_thread", lambda generation_id: None)
    out = _run(ids)
    assert out["chunk_count"] == out["generated_count"] == 3, "25 秒按 10 秒上限硬切成三块,每块都被收下"


def test_这一轮在停_不再提交下一块改口型(dubbed, monkeypatch) -> None:
    """改好第一块之后,用户取消了(或同一张图里别的节点失败了):第二块不再提交、不再计费。等子任务时认停的信号,
    而两块之间此前没人问。"""
    from app.domain.workflows.run_scope import halt_scope

    ids, calls = dubbed
    real = module._generate

    with halt_scope() as halt:
        def generate_then_stop(*args, **kwargs):
            out = real(*args, **kwargs)
            halt.set()
            return out

        monkeypatch.setattr(module, "_generate", generate_then_stop)
        with pytest.raises(WorkflowDomainError) as stopped:
            _run(ids)
    assert stopped.value.key == "wfErr_cancelled" and len(calls) == 1
