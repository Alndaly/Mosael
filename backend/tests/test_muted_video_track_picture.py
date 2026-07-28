"""静音 video 轨:画面留下,声音去掉。

回归。轨道头的静音按钮是**喇叭**图标(`Volume2`/`VolumeX`,文案 trackMute),语义只关音频——
预览一直是这么做的(WebAudioMixer 按 trackMuted 归零增益,画面照旧)。但导出侧把静音轨整个
从 overlay 里剔除了,于是「给画中画轨静音」在成片里表现为**那层画面凭空消失**,而预览里它
还好好地显示着。两侧各有绿测试、断言相反,谁都没发现。

现在画面归属由 app/media/scene.py 决定(前端 sceneModel.ts 是对侧,contracts/scene-cases.json
钉死两者),这里守的是它在真实计划构建里的落地:overlay 还在、它的音频没了。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import Asset, Clip, Project, Sequence, Track, Workspace
from app.domain.render import build_plan_for_sequence
from tests.util import fresh_client


def _seq_with_pip(*, pip_muted: bool) -> str:
    """底轨一个 8s 片段 + 上层一个 4s 画中画;返回 sequence id。"""
    with SessionLocal() as db:
        ws = Workspace(name="W")
        db.add(ws)
        db.flush()
        pr = Project(workspace_id=ws.id, name="P")
        db.add(pr)
        db.flush()
        asset = Asset(workspace_id=ws.id, project_id=pr.id, name="v.mp4", kind="video", file_key="v.mp4")
        db.add(asset)
        db.flush()
        seq = Sequence(workspace_id=ws.id, project_id=pr.id, name="S")
        # position 小 = 时间线靠上;所以 pip(0)在上、base(1)在下。
        pip_track = Track(sequence=seq, kind="video", name="PIP", position=0, muted=pip_muted)
        base_track = Track(sequence=seq, kind="video", name="V1", position=1)
        db.add_all([seq, pip_track, base_track])
        db.flush()
        db.add_all([
            Clip(workspace_id=ws.id, sequence_id=seq.id, track_id=base_track.id, asset_id=asset.id,
                 timeline_start=0, src_in=0, src_out=8),
            Clip(workspace_id=ws.id, sequence_id=seq.id, track_id=pip_track.id, asset_id=asset.id,
                 timeline_start=0, src_in=0, src_out=4),
        ])
        db.commit()
        return seq.id


def test_unmuted_pip_contributes_picture_and_audio() -> None:
    """基准线:没静音时,画面和声音都在——好让下面的断言证明的是静音的效果,不是别的。"""
    fresh_client()
    seq_id = _seq_with_pip(pip_muted=False)
    with SessionLocal() as db:
        plan = build_plan_for_sequence(db, seq_id)
    assert len(plan.overlays) == 1
    assert len(plan.audio_overlays) == 1


def test_muted_pip_keeps_its_picture() -> None:
    """核心回归:静音不该让这层画面从成片里消失。"""
    fresh_client()
    seq_id = _seq_with_pip(pip_muted=True)
    with SessionLocal() as db:
        plan = build_plan_for_sequence(db, seq_id)
    assert len(plan.overlays) == 1, "静音的画中画轨在导出里丢了画面——预览里它是显示的"
    assert plan.overlays[0].duration == 4


def test_muted_pip_drops_its_audio() -> None:
    """另一半:静音必须真的静音,否则这个按钮就没用了。"""
    fresh_client()
    seq_id = _seq_with_pip(pip_muted=True)
    with SessionLocal() as db:
        plan = build_plan_for_sequence(db, seq_id)
    assert plan.audio_overlays == (), "静音轨的音频仍被混入"


def test_muted_base_track_keeps_picture_and_loses_audio() -> None:
    """base 轨同一条规则:画面是画面,声音是声音。"""
    fresh_client()
    with SessionLocal() as db:
        ws = Workspace(name="W")
        db.add(ws)
        db.flush()
        pr = Project(workspace_id=ws.id, name="P")
        db.add(pr)
        db.flush()
        asset = Asset(workspace_id=ws.id, project_id=pr.id, name="v.mp4", kind="video", file_key="v.mp4")
        db.add(asset)
        db.flush()
        seq = Sequence(workspace_id=ws.id, project_id=pr.id, name="S")
        base = Track(sequence=seq, kind="video", name="V1", position=0, muted=True)
        db.add_all([seq, base])
        db.flush()
        db.add(Clip(workspace_id=ws.id, sequence_id=seq.id, track_id=base.id, asset_id=asset.id,
                    timeline_start=0, src_in=0, src_out=5))
        db.commit()
        seq_id = seq.id
    with SessionLocal() as db:
        plan = build_plan_for_sequence(db, seq_id)
    assert len(plan.video_segments) == 1, "静音的底轨丢了画面"
    assert plan.mute_base_audio is True, "静音的底轨仍在出声"


def test_empty_bottom_track_does_not_become_base() -> None:
    """回归:base 是最底「有画面片段」的轨。空底轨当 base 会让整个渲染变成「没有片段可渲染」。"""
    fresh_client()
    with SessionLocal() as db:
        ws = Workspace(name="W")
        db.add(ws)
        db.flush()
        pr = Project(workspace_id=ws.id, name="P")
        db.add(pr)
        db.flush()
        asset = Asset(workspace_id=ws.id, project_id=pr.id, name="v.mp4", kind="video", file_key="v.mp4")
        db.add(asset)
        db.flush()
        seq = Sequence(workspace_id=ws.id, project_id=pr.id, name="S")
        has_media = Track(sequence=seq, kind="video", name="V1", position=0)
        empty_below = Track(sequence=seq, kind="video", name="V0", position=1)
        db.add_all([seq, has_media, empty_below])
        db.flush()
        db.add(Clip(workspace_id=ws.id, sequence_id=seq.id, track_id=has_media.id, asset_id=asset.id,
                    timeline_start=0, src_in=0, src_out=6))
        db.commit()
        seq_id = seq.id
    with SessionLocal() as db:
        plan = build_plan_for_sequence(db, seq_id)
    # 有画面的那条轨被提为 base(走 segments),而不是降级成 overlay。
    assert len(plan.video_segments) == 1
    assert plan.overlays == ()
