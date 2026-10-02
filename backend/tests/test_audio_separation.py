"""人声/背景音分离是一个**能力**,不是配音流程里的一步(ADR-0016)。

真机上撞到的那一步:译配把原声整轨静音之后,**背景音乐也没了** —— 说话声和音乐混在同一条
轨上,而"静音"分不开它们。缺的操作是分离。

这里钉的是这个能力的四条边界,而不是某个模型分得好不好(那是引擎的事,不是我们的):

1. 可用性是**问出来的**,不是配置出来的;
2. 分离**产出新素材**,原素材一个字节不动;
3. 少给一条 stem 就报错,不静默返回半份;
4. 用户明确选择分离时,能力不可用就失败,绝不静默改成整轨静音。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.domain import audio_capabilities
from app.ai.providers.contracts.separation import (
    BACKGROUND,
    VOCALS,
    SeparationError,
    SeparationRequest,
)


class _FakeAdapter:
    engine_id = "fake"
    label_key = "sepEngine_fake"

    def __init__(self, *, ready: bool = True, stems: tuple[str, ...] = (VOCALS, BACKGROUND)) -> None:
        self._ready = ready
        self._stems = stems
        self.installed = 0

    def runtime_ready(self) -> bool:
        return self._ready

    def ensure_runtime(self) -> None:
        self.installed += 1
        self._ready = True

    def separate(self, request: SeparationRequest, out_dir: Path) -> dict[str, Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        made = {}
        for stem in self._stems:
            path = out_dir / f"{stem}.wav"
            path.write_bytes(b"RIFF....WAVE")
            made[stem] = path
        return made


def _no_engine(*_args):
    from app.domain.audio_capabilities import SeparationProviderUnavailable

    raise SeparationProviderUnavailable("separationErr_noEngine")


class Test能力可用性是问出来的:
    def test_本机引擎是能力表的内置提供方_插件连接和它并列(self) -> None:
        """挑哪一家不再是进程全局的注册表(ADR 0032):本机引擎登记成 `audio_separation` 的内置提供方,
        不点名时按这个人的默认挑,没定默认用内置的。"""
        from app.core.db import SessionLocal
        from app.domain import capabilities
        from app.domain.audio_capabilities import SEPARATION

        with SessionLocal() as db:
            picked = capabilities.pick(db, None, SEPARATION, None)
            assert picked.builtin and picked.id == "builtin:demucs"
            assert capabilities.pick(db, None, SEPARATION, "builtin:demucs").id == "builtin:demucs"

    def test_available_真的去问引擎(self, monkeypatch) -> None:
        """它是配音流程决定"拆还是静音"的那个判据。恒真的话,一台没装引擎的机器会走进
        分离那条路,然后在里面失败 —— 而那条路的全部意义就是"问得到才做"。"""
        from app.domain import audio_capabilities
        from app.domain.assets import separation

        def none(*_args):
            raise audio_capabilities.SeparationProviderUnavailable("separationErr_noEngine")

        monkeypatch.setattr(audio_capabilities, "separation_adapter", none)
        assert separation.available(None, None) is False
        monkeypatch.setattr(audio_capabilities, "separation_adapter", lambda *_a: _FakeAdapter(ready=False))
        assert separation.available(None, None) is False
        monkeypatch.setattr(audio_capabilities, "separation_adapter", lambda *_a: _FakeAdapter(ready=True))
        assert separation.available(None, None) is True

    def test_重复的引擎_id_在装配时就失败(self) -> None:
        """和生成、语音那两张表同一条:后一次导入静默覆盖前一次,是查不出来的那种错。"""
        from app.ai.providers.registry import _index_separation_adapters

        with pytest.raises(RuntimeError, match="duplicate"):
            _index_separation_adapters((_FakeAdapter(), _FakeAdapter()))


class Test分离产出新素材:
    def test_原素材不动__拆出两份新的(self, monkeypatch, tmp_path) -> None:
        from app.core.db import SessionLocal
        from app.db.models import Asset
        from app.domain.assets import separation
        from tests.util import fresh_client

        client = fresh_client()
        workspace = client.post("/api/workspaces", json={"name": "W"}).json()

        source = tmp_path / "talk.wav"
        source.write_bytes(b"RIFF....WAVE")
        with SessionLocal() as db:
            asset = Asset(workspace_id=workspace["id"], kind="audio", name="访谈", file_key="k")
            db.add(asset)
            db.commit()
            asset_id, before = asset.id, asset.file_key

            monkeypatch.setattr(audio_capabilities, "separation_adapter", lambda *_a: _FakeAdapter())
            monkeypatch.setattr(separation, "_source_path", lambda one: source)

            made = separation.separate_asset(db, asset, engine="")
            assert made.vocals.id != asset_id and made.background.id != asset_id
            assert made.vocals.kind == "audio" and made.background.kind == "audio"
            #: 名字要让人在素材库里一眼看出它是从哪儿来的。
            assert "人声" in made.vocals.name and "访谈" in made.vocals.name
            assert "背景音" in made.background.name

            db.refresh(asset)
            assert asset.file_key == before, "原素材一个字节都不该动"

    def test_少给一条就报错__不静默返回半份(self, monkeypatch, tmp_path) -> None:
        """少的那条会一路空到成片里 —— 而那时已经离这里很远了。"""
        from app.core.db import SessionLocal
        from app.db.models import Asset
        from app.domain.assets import separation
        from tests.util import fresh_client

        client = fresh_client()
        workspace = client.post("/api/workspaces", json={"name": "W"}).json()
        source = tmp_path / "talk.wav"
        source.write_bytes(b"RIFF....WAVE")
        with SessionLocal() as db:
            asset = Asset(workspace_id=workspace["id"], kind="audio", name="访谈", file_key="k")
            db.add(asset)
            db.commit()
            half = _FakeAdapter(stems=(VOCALS,))
            monkeypatch.setattr(audio_capabilities, "separation_adapter", lambda *_a: half)
            monkeypatch.setattr(separation, "_source_path", lambda one: source)
            with pytest.raises(SeparationError, match="背景音"):
                separation.separate_asset(db, asset, engine="")

    def test_没引擎时说得出是没引擎(self, monkeypatch) -> None:
        from app.db.models import Asset
        from app.domain.assets import separation

        monkeypatch.setattr(audio_capabilities, "separation_adapter", _no_engine)
        with pytest.raises(SeparationError, match="没有可用"):
            separation.separate_asset(None, Asset(workspace_id="w", kind="audio", name="x"), engine="")


class Test契约不认识任何一个引擎:
    def test_契约里不出现具体引擎(self) -> None:
        """契约反向依赖某个 Adapter,这一层就白分了(ADR-0010)。"""
        from pathlib import Path as _Path

        text = _Path("app/ai/providers/contracts/separation.py").read_text(encoding="utf-8")
        for name in ("demucs", "torch", "spleeter", "httpx"):
            assert name not in text.lower().replace("demucs 叫", ""), name

    def test_worker_不许_import_app(self) -> None:
        """它跑在**引擎自己那个 venv** 里,sys.path 上没有本仓库 —— import 会在运行时炸,
        而单测里它从来不被 import,所以炸不出来。用户看到的是"转半天然后一句看不懂的报错"。"""
        from pathlib import Path as _Path

        text = _Path("app/ai/runtime/workers/separation.py").read_text(encoding="utf-8")
        assert "import app." not in text and "from app." not in text


class Test配音流程忠实执行用户选择:
    def test_没装引擎时明确失败__不擅自静音(self, monkeypatch) -> None:
        from app.domain.assets import separation
        from app.domain.voices import original_audio
        from tests.util import fresh_client

        fresh_client()
        monkeypatch.setattr(separation, "available", lambda *_a, **_k: False)
        seen: list[str] = []
        import app.domain.sequences.operations as ops

        monkeypatch.setattr(ops, "set_track_state", lambda *a, **k: seen.append("state"))
        monkeypatch.setattr(ops, "set_clip_effects", lambda *a, **k: seen.append("effects"))
        with pytest.raises(original_audio.OriginalAudioError, match="分离引擎"):
            original_audio.apply_original_audio("s1", "dub", "separate", actor_id=None)
        assert seen == [], "用户选的是分离，不得偷偷改成静音"

    def test_分离可用时_画面留着_原声换成背景音_撤得回来(self, monkeypatch) -> None:
        """成功那条路,在**真的时间线**上看成片会是什么样。

        译配把原片放在视频轨上。此前这里把视频片段直接指向背景音素材 —— 视频轨上的纯音频素材
        既不算画面、也不进混音,成片里那一段只剩静音(真机反馈:选了 separate 实际直接静音)。
        当时的测试只摆了一条假的音频轨,所以没看出来。
        """
        from app.core.db import SessionLocal
        from app.db.models import Asset, Clip, Project, Sequence, Track, Workspace
        from app.domain.assets import separation as sep
        from app.domain.render import build_plan_for_sequence
        from app.domain.sequences.history import redo, undo
        from app.domain.voices import original_audio
        from tests.util import fresh_client

        fresh_client()
        with SessionLocal() as db:
            ws = Workspace(name="W")
            db.add(ws)
            db.flush()
            project = Project(workspace_id=ws.id, name="P")
            db.add(project)
            db.flush()
            seq = Sequence(workspace_id=ws.id, project_id=project.id, name="S")
            video = Track(sequence=seq, kind="video", name="V1", position=0)
            dub = Track(sequence=seq, kind="audio", name="A1", position=1, role="dub")
            footage = Asset(workspace_id=ws.id, kind="video", name="原片", file_key="media/o.mp4")
            background = Asset(workspace_id=ws.id, kind="audio", name="原片 · 背景音", file_key="media/bg.wav")
            voice = Asset(workspace_id=ws.id, kind="audio", name="配音", file_key="media/d.wav")
            db.add_all([seq, video, dub, footage, background, voice])
            db.flush()
            db.add_all([
                Clip(workspace_id=ws.id, sequence_id=seq.id, track_id=video.id, asset_id=footage.id,
                     timeline_start=0, src_in=2, src_out=12, speed=1.25, gain=0.8),
                #: 配音轨上只有 3–5 秒这一段,其余是空档 —— 背景音不能因为"那一段空着"就被塞进配音轨。
                Clip(workspace_id=ws.id, sequence_id=seq.id, track_id=dub.id, asset_id=voice.id,
                     timeline_start=3, src_in=0, src_out=2),
            ])
            db.commit()
            ids = (seq.id, dub.id, footage.id, background.id)

        made = type("M", (), {"background": type("A", (), {"id": ids[3]})()})()
        separated: list[tuple[str, tuple[float, float]]] = []
        monkeypatch.setattr(sep, "available", lambda *_a, **_k: True)
        monkeypatch.setattr(sep, "separate_asset", lambda db, asset, **k: separated.append((asset.id, k["span"])) or made)

        seq_id, dub_id, footage_id, background_id = ids
        assert original_audio.apply_original_audio(seq_id, dub_id, "separate", actor_id=None) == "separate"
        assert separated == [(footage_id, (2, 12))], "只拆这一段用到的源区间"

        def check(db) -> None:
            plan = build_plan_for_sequence(db, seq_id)
            [base] = [segment for segment in plan.video_segments if segment.kind == "clip"]
            assert base.source.asset_id == footage_id, "画面还是原片"
            assert base.muted, "原片自己的声音关掉了"
            [bed] = [item for item in plan.audio_overlays if item.source.asset_id == background_id]
            # 拆出来的背景音从源的第 2 秒开始:片段的入出点减掉这个偏移,对上的还是同一句话。
            assert (bed.start, bed.source.src_in, bed.source.src_out, bed.speed) == (0, 0, 10, 1.25), "背景音和画面对齐"
            track = db.scalar(select(Clip).where(Clip.asset_id == background_id)).track
            assert track.id != dub_id and not track.role

        with SessionLocal() as db:
            check(db)
            undo(db, seq_id)
            plan = build_plan_for_sequence(db, seq_id)
            assert not plan.video_segments[0].muted
            assert all(item.source.asset_id != background_id for item in plan.audio_overlays)
            redo(db, seq_id)
            db.commit()
        with SessionLocal() as db:
            check(db)

    def test_分到一半失败_时间线一点没动(self, monkeypatch) -> None:
        """失败必须上报；这之前不能留下半套背景音轨。"""
        from app.core.db import SessionLocal
        from app.db.models import Asset, Clip, Project, Sequence, Track, Workspace
        from app.domain.assets import separation as sep
        from app.domain.sequences import operations as ops
        from app.domain.voices import original_audio
        from tests.util import fresh_client

        fresh_client()
        with SessionLocal() as db:
            ws = Workspace(name="W")
            db.add(ws)
            db.flush()
            project = Project(workspace_id=ws.id, name="P")
            db.add(project)
            db.flush()
            seq = Sequence(workspace_id=ws.id, project_id=project.id, name="S")
            video = Track(sequence=seq, kind="video", name="V1", position=0)
            dub = Track(sequence=seq, kind="audio", name="A1", position=1, role="dub")
            first = Asset(workspace_id=ws.id, kind="video", name="一", file_key="media/1.mp4")
            second = Asset(workspace_id=ws.id, kind="video", name="二", file_key="media/2.mp4")
            voice = Asset(workspace_id=ws.id, kind="audio", name="配音", file_key="media/d.wav")
            db.add_all([seq, video, dub, first, second, voice])
            db.flush()
            db.add_all([
                Clip(workspace_id=ws.id, sequence_id=seq.id, track_id=video.id, asset_id=first.id,
                     timeline_start=0, src_in=0, src_out=5),
                Clip(workspace_id=ws.id, sequence_id=seq.id, track_id=video.id, asset_id=second.id,
                     timeline_start=5, src_in=0, src_out=5),
                Clip(workspace_id=ws.id, sequence_id=seq.id, track_id=dub.id, asset_id=voice.id,
                     timeline_start=0, src_in=0, src_out=10),
            ])
            db.commit()
            seq_id, dub_id, revision = seq.id, dub.id, seq.revision
        calls = iter([type("M", (), {"background": type("A", (), {"id": "bg"})()})()])

        def separate(db, asset, **k):
            try:
                return next(calls)
            except StopIteration:
                raise SeparationError("第二段炸了") from None

        monkeypatch.setattr(sep, "available", lambda *_a, **_k: True)
        monkeypatch.setattr(sep, "separate_asset", separate)
        monkeypatch.setattr(ops, "detach_clip_audio", lambda *a, **k: pytest.fail("不该动时间线"))
        with pytest.raises(original_audio.OriginalAudioError, match="第二段炸了"):
            original_audio.apply_original_audio(seq_id, dub_id, "separate", actor_id=None)
        with SessionLocal() as db:
            assert db.get(Sequence, seq_id).revision == revision


class Test当作任务跑:
    def test_没有引擎时不排队__当场说清楚(self, monkeypatch) -> None:
        """排一个注定失败的任务,只是把同一句话推迟十秒说 —— 而中间那十秒用户以为它在干活。"""
        from app.db.models import Asset
        from app.domain.assets import separation

        monkeypatch.setattr(separation, "available", lambda *_a, **_k: False)
        with pytest.raises(SeparationError, match="管理 → 引擎"):
            separation.start_separation_job(
                None, asset=Asset(workspace_id="w", kind="audio", name="x", file_key="k"), created_by=None
            )

    def test_只有音频和视频能拆(self, monkeypatch) -> None:
        from app.db.models import Asset
        from app.domain.assets import separation

        monkeypatch.setattr(separation, "available", lambda *_a, **_k: True)
        with pytest.raises(SeparationError, match="只有音频或视频"):
            separation.start_separation_job(
                None, asset=Asset(workspace_id="w", kind="image", name="x", file_key="k"), created_by=None
            )

    def test_两份产出都记着自己是从哪儿来的(self, monkeypatch, tmp_path) -> None:
        """派生关系放在**新素材**上,原素材一个字不改(和转 GIF 同款)。
        没有它,素材库里多出两份来历不明的音频,而"人声还是背景音"只能靠名字猜。"""
        from app.core.db import SessionLocal
        from app.db.models import Asset, Job
        from app.domain.assets import separation
        from tests.util import fresh_client

        client = fresh_client()
        workspace = client.post("/api/workspaces", json={"name": "W"}).json()
        source = tmp_path / "talk.wav"
        source.write_bytes(b"RIFF....WAVE")
        with SessionLocal() as db:
            asset = Asset(workspace_id=workspace["id"], kind="audio", name="访谈", file_key="k")
            job = Job(workspace_id=workspace["id"], kind="separate_audio", status="queued")
            db.add_all([asset, job])
            db.commit()
            asset_id, job_id = asset.id, job.id

        monkeypatch.setattr(audio_capabilities, "separation_adapter", lambda *_a: _FakeAdapter())
        monkeypatch.setattr(separation, "_source_path", lambda one: source)
        separation._job_body(job_id, asset_id, "")

        with SessionLocal() as db:
            done = db.get(Job, job_id)
            assert done.status == "succeeded"
            stems = {
                db.get(Asset, done.result["vocals_asset_id"]).media_info["stem"]: done.result["vocals_asset_id"],
                db.get(Asset, done.result["background_asset_id"]).media_info["stem"]: done.result[
                    "background_asset_id"
                ],
            }
            assert set(stems) == {VOCALS, BACKGROUND}
            for one in stems.values():
                assert db.get(Asset, one).derived_from == [{"asset_id": asset_id, "op": "separate"}]


class Test节点上的引擎是选出来的:
    def test_选项是能力表里的提供方(self) -> None:
        """节点上的引擎曾经是一格自由文本,后来是写死的 `auto / demucs`;现在从能力表现查(ADR 0032):
        本机引擎、配好的分离插件都在下拉里,留空 = 按运行者的默认。"""
        from app.domain.workflows import NODE_TYPES

        spec = NODE_TYPES["separate_audio"]["config"]["engine"]
        assert spec["options_from"] == "providers.audio_separation" and "options" not in spec and "default" not in spec
