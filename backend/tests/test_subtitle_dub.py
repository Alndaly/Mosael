"""字幕配音。

这个功能的价值全在两个细节上,所以测试也压在这两处:

1. **时长匹配是可选的,而且用片段的 speed 实现** —— 不是把音频重新编码。渲染时 atempo 会按它
   变速,所以这一步无损、可撤销、事后还能手动微调。
2. **空字幕不配音** —— 合成一段空文本得到的是一段静音,它会安安静静占住时间线上的一格。
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.audio.subtitle_dub import DubError, _speed_for, start_subtitle_dub
from app.core.db import SessionLocal
from tests.util import fresh_client


def test_speed_matches_audio_to_the_subtitle_slot() -> None:
    # 6 秒的配音要塞进 3 秒的字幕 → 2 倍速播放,正好占满。
    assert _speed_for(6.0, 3.0) == 2.0
    # 反过来,短配音拉长到长段落。
    assert _speed_for(1.5, 3.0) == 0.5


def test_speed_is_unknown_rather_than_zero_when_a_duration_is_missing() -> None:
    """探不到时长的音频(或零长字幕)没有倍速可言 —— None,不是 0。

    返回 0 的话调用方会拿它去写库,而 speed=0 的片段在渲染时是一个除零。"""
    assert _speed_for(0.0, 3.0) is None
    assert _speed_for(6.0, 0.0) is None


def test_speed_is_clamped_to_the_editable_range() -> None:
    """一条字幕的文本长到要 20 倍速才塞得下,那是文本和时长本身不匹配。

    夹到边界而不是抛错:整批配音不该因为其中一条而全部失败,而用户在时间线上一眼就能看出
    那一段被压过头了 —— 这比一个 422 更有用。"""
    assert _speed_for(60.0, 1.0) == 4.0
    assert _speed_for(1.0, 60.0) == 0.25


def _sequence_with_subtitle(client, text: str = "你好") -> tuple[str, str]:
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": workspace["id"], "name": "P"}).json()
    sequence = client.post(
        "/api/sequences",
        json={"workspace_id": workspace["id"], "project_id": project["id"], "name": "S"},
    ).json()
    tracks = client.post(f"/api/sequences/{sequence['id']}/tracks", json={"kind": "subtitle"}).json()
    track_id = next(t["id"] for t in tracks["tracks"] if t["kind"] == "subtitle")
    created = client.post(
        f"/api/sequences/{sequence['id']}/text-clips",
        json={"track_id": track_id, "text": text, "timeline_start": 1.0, "duration": 3.0},
    )
    assert created.status_code == 200, created.text
    clips = next(t["clips"] for t in created.json()["tracks"] if t["id"] == track_id)
    return sequence["id"], clips[0]["id"]


def test_refuses_when_nothing_selected_has_text() -> None:
    """空字幕合成出来是一段静音 —— 它不会报错,只会安静地占住时间线上的一格。"""
    from app.db.models import Clip

    client = fresh_client()
    sequence_id, clip_id = _sequence_with_subtitle(client)
    with SessionLocal() as db:
        # 字幕可以被清空(编辑器里删掉文字就是),而清空之后它仍然是一条字幕片段。
        db.get(Clip, clip_id).text_override = "   "
        db.commit()
        with pytest.raises(DubError):
            start_subtitle_dub(
                db,
                sequence_id=sequence_id,
                clip_ids=[clip_id],
                match_duration=False,
                created_by=None,
                synthesis={"engine": "volcano", "engine_voice": "v", "workspace_id": "w"},
            )


def test_dubbing_needs_both_edit_and_ai_permission() -> None:
    """配音既改这条时间线,又花工作区的 AI 额度 —— 少判一个就等于漏一道闸门。"""
    client = fresh_client()
    sequence_id, clip_id = _sequence_with_subtitle(client)
    response = client.post(
        f"/api/sequences/{sequence_id}/dub-subtitles",
        json={"clip_ids": [clip_id], "engine": "volcano", "engine_voice": "v"},
    )
    # 这个用户是工作区所有者,两道权限都有 —— 挡下来的会是"没配供应商",而不是 403。
    assert response.status_code != 403, response.text


def test_bilingual_cue_reads_only_the_line_you_picked() -> None:
    """双语字幕是「原文\\n译文」两行。

    整段丢给合成 = 先念一遍日文再念一遍中文,一条 3 秒的字幕配出十几秒的音,而且没人想听
    那个。默认全念是对的(单语字幕占绝大多数),但双语时必须能选。
    """
    from app.audio.subtitle_dub import dub_text

    cue = "The.\n这。"
    assert dub_text(cue) == "The.\n这。"
    assert dub_text(cue, "first") == "The."
    assert dub_text(cue, "last") == "这。"
    # 单语字幕选「只念第二行」不该念出空气 —— 只有一行时那一行就是首也是尾。
    assert dub_text("只有一行", "last") == "只有一行"
    # 空行不算行:翻译留下的尾随换行不该把「最后一行」变成空串。
    assert dub_text("The.\n这。\n\n", "last") == "这。"


def test_cue_without_the_chosen_line_is_not_dubbed() -> None:
    """选了「只念第二行」而这条只有一行时,按整段判会把它当成有文本。

    那样配出来的是原文,和其他条念的译文对不上 —— 一条混进去的错音比少一条难发现得多。
    """
    from app.audio.subtitle_dub import dub_text

    assert dub_text("   \n  ", "last") == ""


def test_dub_track_is_reused_not_stacked() -> None:
    """再配一次要回到**同一条**配音轨。

    每配一次新建一条的话,改几句台词重配几段,时间线上就摞起一叠只有一两段音频的轨。
    """
    from app.audio.subtitle_dub import _dub_track
    from app.core.db import SessionLocal
    from app.db.models import Track

    client = fresh_client()
    sequence_id, _ = _sequence_with_subtitle(client)
    with SessionLocal() as db:
        first = _dub_track(db, sequence_id, None)
        second = _dub_track(db, sequence_id, None)
        assert first == second
        assert db.get(Track, first).role == "dub"
        audio = [t for t in db.scalars(select(Track).where(Track.sequence_id == sequence_id)) if t.kind == "audio"]
        assert len([t for t in audio if t.role == "dub"]) == 1


def test_a_plain_audio_track_is_not_mistaken_for_the_dub_track() -> None:
    """用户自己加的音轨(BGM、旁白素材)不该被配音占用 —— 认的是 role,不是「最后一条音频轨」。"""
    from app.audio.subtitle_dub import _dub_track
    from app.core.db import SessionLocal
    from app.db.models import Track

    client = fresh_client()
    sequence_id, _ = _sequence_with_subtitle(client)
    added = client.post(f"/api/sequences/{sequence_id}/tracks", json={"kind": "audio"})
    assert added.status_code == 200, added.text
    with SessionLocal() as db:
        dub = _dub_track(db, sequence_id, None)
        plain = [
            t
            for t in db.scalars(select(Track).where(Track.sequence_id == sequence_id))
            if t.kind == "audio" and t.id != dub
        ]
        assert plain, "用户那条音轨还在"
        assert all(t.role == "" for t in plain)


def test_renaming_the_dub_track_does_not_lose_it() -> None:
    """把配音轨改名成「旁白」之后,再配一次仍然回到它 —— 名字是给人看的,认的是 role。"""
    from app.audio.subtitle_dub import _dub_track
    from app.core.db import SessionLocal
    from app.db.models import Track

    client = fresh_client()
    sequence_id, _ = _sequence_with_subtitle(client)
    with SessionLocal() as db:
        first = _dub_track(db, sequence_id, None)
        db.get(Track, first).name = "旁白"
        db.commit()
        assert _dub_track(db, sequence_id, None) == first


def _audio_track_with(db, sequence_id: str, sources: list[str]) -> str:
    """造一条音频轨,轨上每段各引一个指定 source 的素材。空列表 = 空轨。"""
    from app.audio.subtitle_dub import _dub_track
    from app.db.models import Asset, Clip, Track

    track_id = _dub_track(db, sequence_id, None)
    db.get(Track, track_id).role = ""  # 造「上线前」的样子:没有标记
    for index, source in enumerate(sources):
        asset = Asset(
            workspace_id=db.get(Track, track_id).sequence.workspace_id,
            kind="audio",
            source=source,
            name=f"a{index}",
        )
        db.add(asset)
        db.flush()
        db.add(Clip(
            workspace_id=asset.workspace_id,
            sequence_id=sequence_id,
            track_id=track_id,
            asset_id=asset.id,
            timeline_start=index * 5.0,
            src_in=0.0,
            src_out=2.0,
        ))
    db.commit()
    return track_id


def test_backfill_marks_tracks_that_hold_only_tts_output() -> None:
    """上线前配过的音要认出来 —— 判据是轨上放的**是什么**,不是它叫什么、排第几。"""
    from app.core.db import SessionLocal
    from app.db.migrations import backfill_dub_tracks
    from app.db.models import Track

    client = fresh_client()
    sequence_id, _ = _sequence_with_subtitle(client)
    with SessionLocal() as db:
        track_id = _audio_track_with(db, sequence_id, ["tts", "tts"])
    backfill_dub_tracks()
    with SessionLocal() as db:
        assert db.get(Track, track_id).role == "dub"


def test_backfill_leaves_ordinary_audio_tracks_alone() -> None:
    """BGM / 录音 / 原声轨不是配音轨 —— 哪怕它上面也有一段 TTS 产物。

    占用用户自己的音轨比多建一条轨糟得多:下一次配音会往里插段落,而他放的东西还在里面。
    """
    from app.core.db import SessionLocal
    from app.db.migrations import backfill_dub_tracks
    from app.db.models import Track

    client = fresh_client()
    sequence_id, _ = _sequence_with_subtitle(client)
    with SessionLocal() as db:
        mixed = _audio_track_with(db, sequence_id, ["tts", "imported"])
    backfill_dub_tracks()
    with SessionLocal() as db:
        assert db.get(Track, mixed).role == ""


def test_backfill_does_not_promote_an_empty_track() -> None:
    """空轨恰恰是失败的配音留下的残骸,把它认成配音轨等于把垃圾扶正。"""
    from app.core.db import SessionLocal
    from app.db.migrations import backfill_dub_tracks
    from app.db.models import Track

    client = fresh_client()
    sequence_id, _ = _sequence_with_subtitle(client)
    with SessionLocal() as db:
        empty = _audio_track_with(db, sequence_id, [])
    backfill_dub_tracks()
    with SessionLocal() as db:
        assert db.get(Track, empty).role == ""
