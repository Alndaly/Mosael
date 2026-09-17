"""人声/背景音分离是一个**能力**,不是配音流程里的一步(ADR-0016)。

真机上撞到的那一步:译配把原声整轨静音之后,**背景音乐也没了** —— 说话声和音乐混在同一条
轨上,而"静音"分不开它们。缺的操作是分离。

这里钉的是这个能力的四条边界,而不是某个模型分得好不好(那是引擎的事,不是我们的):

1. 可用性是**问出来的**,不是配置出来的;
2. 分离**产出新素材**,原素材一个字节不动;
3. 少给一条 stem 就报错,不静默返回半份;
4. 没装引擎时,配音流程**退回静音**而不是失败。
"""

from __future__ import annotations

from pathlib import Path

import pytest

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


class Test能力可用性是问出来的:
    def test_一个引擎都跑不起来时就是不可用(self, monkeypatch) -> None:
        """**不是先调一次再看报错** —— 那一次调用可能已经等了十分钟或者花了钱。"""
        from app.ai.providers import registry

        monkeypatch.setattr(registry, "SEPARATION_ADAPTERS", {"fake": _FakeAdapter(ready=False)})
        assert registry.get_separation_adapter() is None
        #: 点名仍然拿得到 —— 拿它是为了装,不是为了立刻跑。
        assert registry.get_separation_adapter("fake") is not None

    def test_跑得起来的那个会被挑出来(self, monkeypatch) -> None:
        from app.ai.providers import registry

        ready = _FakeAdapter(ready=True)
        monkeypatch.setattr(
            registry, "SEPARATION_ADAPTERS", {"cold": _FakeAdapter(ready=False), "warm": ready}
        )
        assert registry.get_separation_adapter() is ready

    def test_available_真的去问引擎(self, monkeypatch) -> None:
        """它是配音流程决定"拆还是静音"的那个判据。恒真的话,一台没装引擎的机器会走进
        分离那条路,然后在里面失败 —— 而那条路的全部意义就是"问得到才做"。"""
        from app.domain import separation

        monkeypatch.setattr(separation, "get_separation_adapter", lambda engine="": None)
        assert separation.available() is False
        monkeypatch.setattr(separation, "get_separation_adapter", lambda engine="": _FakeAdapter(ready=False))
        assert separation.available() is False
        monkeypatch.setattr(separation, "get_separation_adapter", lambda engine="": _FakeAdapter(ready=True))
        assert separation.available() is True

    def test_重复的引擎_id_在装配时就失败(self) -> None:
        """和生成、语音那两张表同一条:后一次导入静默覆盖前一次,是查不出来的那种错。"""
        from app.ai.providers.registry import _index_separation_adapters

        with pytest.raises(RuntimeError, match="重复"):
            _index_separation_adapters((_FakeAdapter(), _FakeAdapter()))


class Test分离产出新素材:
    def test_原素材不动__拆出两份新的(self, monkeypatch, tmp_path) -> None:
        from app.core.db import SessionLocal
        from app.db.models import Asset
        from app.domain import separation
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

            monkeypatch.setattr(separation, "get_separation_adapter", lambda engine="": _FakeAdapter())
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
        from app.domain import separation
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
            monkeypatch.setattr(separation, "get_separation_adapter", lambda engine="": half)
            monkeypatch.setattr(separation, "_source_path", lambda one: source)
            with pytest.raises(SeparationError, match="背景音"):
                separation.separate_asset(db, asset, engine="")

    def test_没引擎时说得出是没引擎(self, monkeypatch) -> None:
        from app.db.models import Asset
        from app.domain import separation

        monkeypatch.setattr(separation, "get_separation_adapter", lambda engine="": None)
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


class Test配音流程按可用性退让:
    def test_没装引擎时退回整轨静音__而不是整条流程失败(self, monkeypatch) -> None:
        """**一个没装的可选引擎不该让一条本来能跑完的流程失败**(ADR-0016 决定 4)。

        退回的是"原声全没",不是"原声全在":后者才会让成片里两个人同时说话,而那正是
        用户报回来的那个症状。
        """
        from app.domain.workflows.executors import subjobs

        monkeypatch.setattr(subjobs, "_split_voice_from_music", lambda *a, **k: False)
        seen: list[str] = []

        def fake_set_state(db, sequence_id, state):
            seen.append("muted" if state.muted else "duck")

        import app.domain.sequences.operations as ops

        monkeypatch.setattr(ops, "set_track_state", fake_set_state)

        class _Track:
            def __init__(self) -> None:
                self.id = "t1"
                self.kind = "audio"
                self.muted = False
                self.duck = False
                self.clips = [type("C", (), {"asset_id": "a1"})()]

        class _Seq:
            tracks = [_Track()]

        monkeypatch.setattr(subjobs, "Sequence", type("S", (), {}))
        monkeypatch.setattr(subjobs, "db_get_sequence", lambda *a, **k: _Seq(), raising=False)

        class _DB:
            def get(self, model, key):
                return _Seq()

        applied = subjobs._handle_original_audio(_DB(), "s1", "dub", "separate", actor_id=None)
        assert seen == ["muted"], seen
        #: 退回静音要**报出来** —— 背景音乐跟着没了,用户要从通知里知道,而不是看成片才发现。
        assert applied == "mute_fallback"
        from app.core.i18n import t

        assert "背景音乐" in t(f"dubOriginalAudio_{applied}") and "设置" in t(f"dubOriginalAudio_{applied}")

    def test_分离可用时把片段换成背景音__原素材不动(self, monkeypatch) -> None:
        """成功那条路:片段指向的素材换成背景音那一份,人声那半丢掉。

        改的是**片段指向谁**,不是音频本身 —— 原素材一个字节不动,所以这一步和它上面那几步
        一样撤得回来。
        """
        from app.domain.workflows.executors import subjobs

        made = type("M", (), {"background": type("A", (), {"id": "acc"})(), "vocals": type("V", (), {"id": "voc"})()})()

        class _Clip:
            asset_id = "orig"

        clip = _Clip()

        class _Track:
            id = "t1"
            kind = "audio"
            clips = [clip]

        class _Seq:
            tracks = [_Track()]

        class _DB:
            def get(self, model, key):
                return _Seq() if key == "s1" else type("A", (), {"id": key})()

            def commit(self):
                pass

        monkeypatch.setattr(subjobs, "_carries_audio", lambda track: True)
        import app.domain.separation as sep

        monkeypatch.setattr(sep, "available", lambda engine="": True)
        monkeypatch.setattr(sep, "separate_asset", lambda *a, **k: made)

        assert subjobs._split_voice_from_music(_DB(), "s1", "dub", actor_id=None) is True
        assert clip.asset_id == "acc", "片段该指向背景音那一份"


class Test当作任务跑:
    def test_没有引擎时不排队__当场说清楚(self, monkeypatch) -> None:
        """排一个注定失败的任务,只是把同一句话推迟十秒说 —— 而中间那十秒用户以为它在干活。"""
        from app.db.models import Asset
        from app.domain import separation

        monkeypatch.setattr(separation, "available", lambda engine="": False)
        with pytest.raises(SeparationError, match="先在设置里装"):
            separation.start_separation_job(
                None, asset=Asset(workspace_id="w", kind="audio", name="x", file_key="k"), created_by=None
            )

    def test_只有音频和视频能拆(self, monkeypatch) -> None:
        from app.db.models import Asset
        from app.domain import separation

        monkeypatch.setattr(separation, "available", lambda engine="": True)
        with pytest.raises(SeparationError, match="只有音频或视频"):
            separation.start_separation_job(
                None, asset=Asset(workspace_id="w", kind="image", name="x", file_key="k"), created_by=None
            )

    def test_两份产出都记着自己是从哪儿来的(self, monkeypatch, tmp_path) -> None:
        """派生关系放在**新素材**上,原素材一个字不改(和转 GIF 同款)。
        没有它,素材库里多出两份来历不明的音频,而"人声还是背景音"只能靠名字猜。"""
        from app.core.db import SessionLocal
        from app.db.models import Asset, Job
        from app.domain import separation
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

        monkeypatch.setattr(separation, "get_separation_adapter", lambda engine="": _FakeAdapter())
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
                assert db.get(Asset, one).media_info["derived_from_asset_id"] == asset_id


class Test节点上的引擎是选出来的:
    def test_选项就是注册表里那几个(self) -> None:
        """节点上的引擎曾经是一格自由文本 —— 用户得知道引擎叫什么才填得对。
        选项从注册表读:加一个引擎,下拉里自动多一项,不用改两处。"""
        from app.ai.providers.registry import SEPARATION_ADAPTERS
        from app.domain.workflows import NODE_TYPES

        spec = NODE_TYPES["separate_audio"]["config"]["engine"]
        assert spec["options"] == ["auto", *SEPARATION_ADAPTERS]
        assert spec["default"] == "auto"

    def test_auto_就是不点名(self, monkeypatch) -> None:
        """下拉给的是 auto(和转写节点同一个约定),它和空串必须是同一个意思 ——
        否则选了 auto 反而去找一个叫 auto 的引擎,找不到就说"没有可用引擎"。"""
        from app.ai.providers import registry

        ready = _FakeAdapter(ready=True)
        monkeypatch.setattr(registry, "SEPARATION_ADAPTERS", {"fake": ready})
        assert registry.get_separation_adapter("auto") is ready
        assert registry.get_separation_adapter("") is ready
