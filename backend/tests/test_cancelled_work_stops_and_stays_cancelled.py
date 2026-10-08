"""取消一个任务:**真的停下**(子进程、常驻进程、名额)、**不再落产出**、**不被改写回去**。

此前三条都不成立:

- 几个执行体一上来直接 `job.status = "running"` —— 排队时(等转码 / 合成名额、派发器满了)被取消的任务,轮到它时被写回
  「在跑」、照跑到底、最后记成成功,落终态之后的收拾和回执各跑两遍。付费的配音、播客照样调用。
- 任务里经 `run_logged` 起的 ffmpeg / Demucs、常驻的识别 / 合成进程,取消之后照跑(Demucs 最长一小时、转写一小时),
  占着导出和分离共用的 RENDER_SLOTS;跑完的产出照样进素材库、换到时间线上、覆盖旧逐字稿。

修法是三处:总线的 `start_job` / `finish_job` 是写状态的唯一路(ORM 上守着「终态不回头」);`run_logged` 和常驻进程
登记在任务的取消开关上;执行体在登记产出、改时间线、写逐字稿之前问一句(`ensure_wanted` / 先拿住任务再写)。
"""

from __future__ import annotations

import json
import os
import stat
import sys
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core import abort
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.unit_of_work import unit_of_work
from app.db.models import Asset, Job, PublishAccount, PublishTask, Transcript
from app.domain import jobs as jobs_bus
from app.domain.jobs import (
    CANCELLED_ERROR_KEY,
    JobStateError,
    cancel_job,
    create_job,
    start_job,
    wait_for_idle_jobs,
)
from tests.util import fresh_client, insert_asset

FAKE_SECONDS = 20


def _workspace() -> str:
    client = fresh_client()
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _job(ws: str, kind: str, payload: dict | None = None) -> str:
    with unit_of_work() as db:
        return create_job(db, workspace_id=ws, kind=kind, payload=payload or {}, created_by=None).id


def _cancel(job_id: str) -> None:
    with SessionLocal() as db:
        cancel_job(db, db.get(Job, job_id))
        db.commit()  # 测试是入口:cancel_job 不提交


def _status(job_id: str) -> tuple[str, str]:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        return job.status, job.error_key


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _gone_within(pid: int, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return False


def _wait_for(path: Path, timeout: float = 15) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file() and path.read_text().strip():
            return path.read_text().strip()
        time.sleep(0.05)
    raise AssertionError(f"{path} never appeared")


def _media_asset(ws: str, kind: str, name: str, payload: bytes, filename: str) -> str:
    from app.db.models import new_id
    from app.media.paths import asset_dir, asset_key

    asset_id = new_id()
    directory = asset_dir(ws, asset_id)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).write_bytes(payload)
    with SessionLocal() as db:
        db.add(Asset(id=asset_id, workspace_id=ws, kind=kind, name=name,
                     file_key=asset_key(ws, asset_id, filename), media_info={}))
        db.commit()
    return asset_id


# ---------------------------------------------------------------------------
# 终态不回头
# ---------------------------------------------------------------------------
def test_a_finished_job_cannot_be_written_back_to_running() -> None:
    ws = _workspace()
    job_id = _job(ws, "render")
    _cancel(job_id)
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        with pytest.raises(JobStateError):
            job.status = "running"


def test_start_job_refuses_a_job_cancelled_while_it_was_queued() -> None:
    ws = _workspace()
    job_id = _job(ws, "render")
    _cancel(job_id)
    with unit_of_work() as db:
        assert start_job(db, db.get(Job, job_id)) is False
    assert _status(job_id) == ("failed", CANCELLED_ERROR_KEY)


def test_ensure_wanted_asks_the_job_it_runs_in() -> None:
    """开关没拉下(比如工作流失败了而不是被取消)也认得出:读库里那一份。不在任何任务里就什么都不查。"""
    ws = _workspace()
    job_id = _job(ws, "workflow")
    jobs_bus.ensure_wanted()  # 不在任务里
    token = jobs_bus.set_parent_job(job_id, strict=False)
    try:
        jobs_bus.ensure_wanted()  # 还在排队 / 在跑:有人要
        with unit_of_work() as db:
            jobs_bus.finish_job(db, db.get(Job, job_id), status="failed", error="上游失败")
        with pytest.raises(jobs_bus.JobCancelled):
            jobs_bus.ensure_wanted()
    finally:
        jobs_bus.reset_parent_job(token)


def test_ensure_wanted_believes_the_switch_before_the_cancel_commits() -> None:
    """取消在**提交之前**就拉下开关(_cancel_job_row → kill_job_child):这段时间里库还说「在跑」,开关已经说「不要了」。"""
    pulled = abort.AbortScope()
    pulled.kill()
    with abort.scope(pulled), pytest.raises(jobs_bus.JobCancelled):
        jobs_bus.ensure_wanted()


# ---------------------------------------------------------------------------
# 排队时被取消:轮到它时什么都不做
# ---------------------------------------------------------------------------
def test_a_proxy_cancelled_while_waiting_for_a_slot_stays_cancelled(monkeypatch) -> None:
    from app.domain.assets import proxies
    from app.media.proxy import TRANSCODE_SLOTS

    ws = _workspace()
    video = _media_asset(ws, "video", "片子", b"not-a-video", "clip.mp4")
    monkeypatch.setattr(settings, "generate_proxies", True)
    monkeypatch.setattr(proxies, "audio_proxies_possible", lambda asset: False)
    built: list[str] = []
    monkeypatch.setattr(proxies, "build_proxy", lambda src, dst: built.append(str(src)) or True)
    settled: list[str] = []
    monkeypatch.setitem(jobs_bus._SETTLE_LISTENERS, "probe", lambda db, job: settled.append(job.status))

    # 两个转码名额都占着:这个代理任务在名额上排队,行是 queued。
    TRANSCODE_SLOTS.acquire()
    TRANSCODE_SLOTS.acquire()
    try:
        with unit_of_work() as db:
            job_id = proxies.start_proxy_job(db, db.get(Asset, video), created_by=None).id
        time.sleep(0.3)
        assert _status(job_id)[0] == "queued"
        _cancel(job_id)
    finally:
        TRANSCODE_SLOTS.release()
        TRANSCODE_SLOTS.release()
    assert wait_for_idle_jobs(timeout=30)

    assert _status(job_id) == ("failed", CANCELLED_ERROR_KEY), "取消被执行体改写了"
    assert built == [], "取消了的代理照样转了码"
    assert settled == ["failed"], f"落终态之后的收拾跑了 {len(settled)} 次:{settled}"
    with SessionLocal() as db:
        # 不是停在 pending(那样下次启动补齐扫描会把它再排一次,用户的取消被撤销)。
        assert db.get(Asset, video).media_info.get("proxy_status") == "failed"


def test_a_remote_voice_cancelled_while_queued_never_calls_the_paid_engine(monkeypatch) -> None:
    from app.domain.voices import voices

    ws = _workspace()
    job_id = _job(ws, "tts")
    calls: list[str] = []
    monkeypatch.setattr(voices, "speak_to_file", lambda *a, **k: calls.append("speak"))
    _cancel(job_id)

    voices._run_synthesis_body(job_id, None, "你好", None, "openai", "alloy", 1.0, ws)

    assert calls == [], "排队时取消了的配音照样去调了付费接口"
    assert _status(job_id) == ("failed", CANCELLED_ERROR_KEY)


def test_a_podcast_cancelled_while_queued_never_calls_the_provider(monkeypatch) -> None:
    import app.ai.providers as providers
    from app.domain.voices import voices

    ws = _workspace()
    job_id = _job(ws, "podcast")
    calls: list[str] = []
    monkeypatch.setattr(providers, "synthesize_volcano_podcast", lambda *a, **k: calls.append("podcast"))
    _cancel(job_id)

    voices._run_podcast_body(job_id, ws, None, "材料", "", 0, [], 1.0)

    assert calls == []
    assert _status(job_id) == ("failed", CANCELLED_ERROR_KEY)


def test_a_trim_cancelled_while_queued_never_runs_ffmpeg(monkeypatch) -> None:
    from app.domain.boards import trim

    ws = _workspace()
    video = _media_asset(ws, "video", "片子", b"not-a-video", "clip.mp4")
    job_id = _job(ws, "trim", {"asset_id": video})
    ran: list[object] = []
    monkeypatch.setattr(trim, "run_logged", lambda *a, **k: ran.append(a))
    _cancel(job_id)

    trim._trim_body(job_id, video, 0.0, 1.0, False)

    assert ran == []
    assert _status(job_id) == ("failed", CANCELLED_ERROR_KEY)


def test_a_link_import_cancelled_while_queued_never_downloads(monkeypatch) -> None:
    from app.domain.assets import from_url

    ws = _workspace()
    job_id = _job(ws, "url_import", {"items": [{"url": "https://example.com/v", "title": "v"}], "kind": "video"})
    downloads: list[str] = []
    monkeypatch.setattr(from_url.ytdlp, "download", lambda url, **k: downloads.append(url))
    _cancel(job_id)

    from_url._run(job_id)

    assert downloads == []
    assert _status(job_id) == ("failed", CANCELLED_ERROR_KEY)


def test_a_late_publish_progress_does_not_bring_a_failed_job_back(monkeypatch) -> None:
    """发布器卡住被回收成「失败」之后,又回报了一句中间态:任务留在失败,不被写回「在跑」(也不该抛)。"""
    from app.domain.publish.worker import _sync_job

    ws = _workspace()
    job_id = _job(ws, "publish")
    asset = insert_asset(ws, kind="video", name="成片", file_key="media/x.mp4")
    with unit_of_work() as db:
        account = PublishAccount(workspace_id=ws, platform="douyin", name="号")
        db.add(account)
        db.flush()
        task = PublishTask(workspace_id=ws, account_id=account.id, asset_id=asset, title="t", job_id=job_id,
                           status="running")
        db.add(task)
        db.flush()
        task_id = task.id
    _cancel(job_id)
    with unit_of_work() as db:
        task = db.get(PublishTask, task_id)
        task.status = "login_required"
        _sync_job(db, task)
    assert _status(job_id) == ("failed", CANCELLED_ERROR_KEY)


# ---------------------------------------------------------------------------
# 跑到一半被取消:子进程停下、名额放掉、产出不落
# ---------------------------------------------------------------------------
def test_run_logged_inside_a_job_is_stopped_with_its_whole_tree_on_cancel(tmp_path: Path) -> None:
    from app.core.child_process import run_logged

    grandchild_pid = tmp_path / "grandchild.pid"
    script = (
        "import subprocess, sys, time\n"
        f"p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep({FAKE_SECONDS})'])\n"
        f"open({str(grandchild_pid)!r}, 'w').write(str(p.pid))\n"
        f"time.sleep({FAKE_SECONDS})\n"
    )
    scope = abort.AbortScope()
    outcome: dict[str, object] = {}

    def run() -> None:
        with abort.scope(scope):
            started = time.monotonic()
            outcome["result"] = run_logged([sys.executable, "-c", script], what="测试", capture_output=True,
                                           timeout=FAKE_SECONDS * 2)
            outcome["took"] = time.monotonic() - started

    worker = threading.Thread(target=run)
    worker.start()
    pid = int(_wait_for(grandchild_pid))
    scope.kill()
    worker.join(timeout=10)
    assert not worker.is_alive(), "取消之后 run_logged 还在等子进程"
    assert outcome["result"].returncode != 0
    assert outcome["took"] < FAKE_SECONDS / 2
    assert _gone_within(pid, 5), "子进程起的孙进程没跟着停"


def test_run_logged_outside_a_job_is_untouched() -> None:
    from app.core.child_process import run_logged

    result = run_logged([sys.executable, "-c", "print('ok')"], what="测试", capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and result.stdout.strip() == "ok"


def test_a_resident_worker_request_is_killed_when_its_job_is_cancelled(tmp_path: Path) -> None:
    from app.ai.runtime.errors import RuntimeSetupError
    from app.ai.runtime.worker_pool import ResidentWorker

    script = tmp_path / "worker.py"
    script.write_text(f"import sys, time\nfor line in sys.stdin:\n    time.sleep({FAKE_SECONDS})\n")
    worker = ResidentWorker("fake", sys.executable, str(script), None,
                            decode=lambda line: json.loads(line) if line.startswith("{") else None,
                            noun="识别", kind="asr")
    scope = abort.AbortScope()
    outcome: dict[str, object] = {}

    def ask() -> None:
        with abort.scope(scope):
            try:
                worker.request({"action": "go"}, on_progress=None, timeout=FAKE_SECONDS * 2)
            except RuntimeSetupError as exc:
                outcome["key"] = exc.key

    asking = threading.Thread(target=ask)
    asking.start()
    time.sleep(0.5)
    scope.kill()
    asking.join(timeout=10)
    assert not asking.is_alive(), "取消之后还在等常驻进程回话(占着 ASR / TTS 名额)"
    assert outcome.get("key") == CANCELLED_ERROR_KEY
    assert _gone_within(worker.process.pid, 5)


def test_cancelling_a_separation_stops_demucs_frees_the_slot_and_registers_nothing(tmp_path, monkeypatch) -> None:
    from app.ai.runtime import separation_models, workers
    from app.domain.assets.separation import start_separation_job
    from app.domain.jobs import RENDER_SLOTS

    ws = _workspace()
    source = _media_asset(ws, "audio", "访谈", b"RIFF....WAVEfake", "talk.wav")
    pid_file = tmp_path / "worker.pid"
    script = tmp_path / "fake_separation_worker.py"
    script.write_text(
        "import json, os, sys, time, pathlib\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))\n"
        "payload = json.loads(sys.stdin.read())\n"
        f"time.sleep({FAKE_SECONDS})\n"
        "out = pathlib.Path(payload['out_dir']); out.mkdir(parents=True, exist_ok=True)\n"
        "stems = {}\n"
        "for s in payload['stems']:\n"
        "    p = out / (s + '.wav'); p.write_bytes(b'RIFF....WAVE'); stems[s] = str(p)\n"
        "pathlib.Path(sys.argv[1]).write_text(json.dumps({'stems': stems}))\n"
    )
    monkeypatch.setattr(separation_models, "runtime_ready", lambda engine: True)
    monkeypatch.setattr(separation_models, "managed_venv_python", lambda engine: Path(sys.executable))
    monkeypatch.setattr(workers, "separation_script", lambda: script)
    # as_audio 要真 ffmpeg;这里只关心分离那一步,原样交出源文件。
    from app.domain.assets import separation as separation_module

    monkeypatch.setattr(separation_module, "as_audio", lambda source, work, span=None: source)

    slots_before = RENDER_SLOTS._value
    with unit_of_work() as db:
        job_id = start_separation_job(db, asset=db.get(Asset, source), created_by=None).id
    worker_pid = int(_wait_for(pid_file))
    _cancel(job_id)

    assert _gone_within(worker_pid, 5), "取消之后 Demucs 还在跑"
    assert wait_for_idle_jobs(timeout=30)
    assert RENDER_SLOTS._value == slots_before, "取消了的分离还占着导出 / 分离共用的名额"
    assert _status(job_id) == ("failed", CANCELLED_ERROR_KEY)
    with SessionLocal() as db:
        assert db.scalars(select(Asset).where(Asset.source == "separated")).all() == [], "取消了的分离照样登记了产出"


def test_cancelling_a_proxy_mid_transcode_stops_ffmpeg_and_keeps_the_cancel(tmp_path, monkeypatch) -> None:
    from app.domain.assets import proxies

    ws = _workspace()
    video = _media_asset(ws, "video", "片子", b"not-a-video", "clip.mp4")
    pid_file = tmp_path / "ffmpeg.pid"
    fake_ffmpeg = tmp_path / "ffmpeg"
    fake_ffmpeg.write_text(
        "#!/bin/sh\n"
        f"echo $$ > {pid_file}\n"
        f"sleep {FAKE_SECONDS}\n"
        'for last; do :; done\n'
        'printf proxy > "$last"\n'
    )
    fake_ffmpeg.chmod(fake_ffmpeg.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(settings, "generate_proxies", True)
    monkeypatch.setattr(settings, "ffmpeg", str(fake_ffmpeg))
    monkeypatch.setattr(proxies, "audio_proxies_possible", lambda asset: False)

    with unit_of_work() as db:
        job_id = proxies.start_proxy_job(db, db.get(Asset, video), created_by=None).id
    ffmpeg_pid = int(_wait_for(pid_file))
    _cancel(job_id)

    assert _gone_within(ffmpeg_pid, 5), "取消之后 ffmpeg 还在转"
    assert wait_for_idle_jobs(timeout=30)
    assert _status(job_id) == ("failed", CANCELLED_ERROR_KEY), "取消被改写成了别的"
    with SessionLocal() as db:
        assert db.get(Asset, video).media_info.get("proxy_status") == "failed"


def test_a_cancelled_clip_denoise_leaves_the_timeline_alone(monkeypatch) -> None:
    from app.db.models import Clip
    from app.domain.assets import denoise as denoise_module
    from app.domain.voices.clip_audio import start_clip_audio_job

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sequence = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()
    track = next(t["id"] for t in sequence["tracks"] if t["kind"] == "audio")
    source = insert_asset(ws, kind="audio", name="采访.wav", file_key="media/assets/x/y/a.wav", media_info={"duration": 10})
    added = client.post(f"/api/sequences/{sequence['id']}/clips",
                        json={"track_id": track, "asset_id": source, "timeline_start": 0, "src_in": 0, "src_out": 10})
    assert added.status_code == 200, added.text
    clip_id = next(c["id"] for t in added.json()["tracks"] for c in t["clips"] if c["asset_id"] == source)

    holder: dict[str, str] = {}

    def denoise_then_get_cancelled(db, asset, **_kw):
        # 降噪做完、正要换上时间线的那一刻,用户点了取消。
        _cancel(holder["job_id"])
        made = Asset(workspace_id=asset.workspace_id, kind="audio", name=f"{asset.name} · 降噪",
                     file_key="media/assets/x/z/b.wav", media_info={"duration": 10}, source="denoised")
        db.add(made)
        db.flush()
        return made, "builtin:ffmpeg"

    monkeypatch.setattr(denoise_module, "denoise_asset", denoise_then_get_cancelled)
    with unit_of_work() as db:
        job = start_clip_audio_job(db, sequence_id=sequence["id"], clip_id=clip_id, action="denoise", created_by=None)
        holder["job_id"] = job.id
    assert wait_for_idle_jobs(timeout=30)

    assert _status(holder["job_id"]) == ("failed", CANCELLED_ERROR_KEY)
    with SessionLocal() as db:
        assert db.get(Clip, clip_id).asset_id == source, "取消了的片段降噪照样把时间线上的片段换掉了"


def test_a_cancelled_transcription_keeps_the_old_transcript(tmp_path, monkeypatch) -> None:
    from app.domain.transcripts.operations import SegmentIn, attach_transcript
    from app.domain.voices import transcription

    ws = _workspace()
    asset_id = _media_asset(ws, "audio", "访谈", b"RIFF....WAVEfake", "talk.wav")
    with unit_of_work() as db:
        old = attach_transcript(db, asset_id=asset_id, language="zh",
                                segments=[SegmentIn(start_time=0, end_time=1, text="旧的那份")], source="imported")
        old_id = old.id
    job_id = _job(ws, "transcribe", {"asset_id": asset_id})

    class Chosen:
        engine_id, name, builtin = "fake", "假引擎", False

        def transcribe(self, wav, language):
            _cancel(job_id)  # 识别途中被取消
            return {"language": "zh", "segments": [{"start": 0, "end": 1, "text": "新的那份"}]}

    monkeypatch.setattr(transcription, "transcriber", lambda db, user, provider: Chosen())
    monkeypatch.setattr(transcription, "_extract_audio", lambda source, wav: wav.write_bytes(b"x"))

    transcription._run_transcription_body(job_id, asset_id)

    assert _status(job_id) == ("failed", CANCELLED_ERROR_KEY)
    with SessionLocal() as db:
        kept = db.scalars(select(Transcript).where(Transcript.asset_id == asset_id)).all()
        assert [one.id for one in kept] == [old_id], "取消了的转写照样覆盖了旧逐字稿"


# ---------------------------------------------------------------------------
# 做完的那一刻被取消:产出不进素材库(登记之前问一句,见 jobs.ensure_wanted)
# ---------------------------------------------------------------------------
def _cancel_now() -> None:
    """在执行体里取消它自己所在的任务 —— 和用户在任务中心点「取消」走同一条路。"""
    _cancel(jobs_bus.current_parent_job_id())


def _registered(source: str) -> list[str]:
    with SessionLocal() as db:
        return [one.name for one in db.scalars(select(Asset).where(Asset.source == source))]


def test_a_separation_cancelled_as_it_finishes_registers_no_stems(monkeypatch) -> None:
    from app.domain.assets import separation as separation_module
    from app.domain.assets.separation import BACKGROUND, VOCALS, start_separation_job

    class FinishesThenGetsCancelled:
        engine_id = "fake"

        def runtime_ready(self) -> bool:
            return True

        def separate(self, request, out_dir: Path) -> dict:
            out_dir.mkdir(parents=True, exist_ok=True)
            stems = {}
            for stem in (VOCALS, BACKGROUND):
                stems[stem] = out_dir / f"{stem}.wav"
                stems[stem].write_bytes(b"RIFF....WAVE")
            _cancel_now()
            return stems

    from app.domain import audio_capabilities

    monkeypatch.setattr(audio_capabilities, "separation_adapter", lambda *a, **k: FinishesThenGetsCancelled())
    monkeypatch.setattr(separation_module, "as_audio", lambda source, work, span=None: source)
    ws = _workspace()
    source = _media_asset(ws, "audio", "访谈", b"RIFF....WAVEfake", "talk.wav")
    with unit_of_work() as db:
        job_id = start_separation_job(db, asset=db.get(Asset, source), created_by=None).id
    assert wait_for_idle_jobs(timeout=30)

    assert _status(job_id) == ("failed", CANCELLED_ERROR_KEY)
    assert _registered("separated") == []


def test_a_denoise_cancelled_as_it_finishes_registers_nothing(monkeypatch) -> None:
    from app.domain.assets import denoise as denoise_module
    from app.domain.assets.denoise import start_denoise_job

    class FinishesThenGetsCancelled:
        engine_id = "builtin:fake"
        strengths = ()

        def denoise(self, request, out: Path) -> Path:
            out.write_bytes(b"RIFF....WAVE")
            _cancel_now()
            return out

    monkeypatch.setattr(denoise_module, "ready_adapter", lambda *a, **k: FinishesThenGetsCancelled())
    monkeypatch.setattr(denoise_module, "as_audio", lambda source, work: source)
    ws = _workspace()
    source = _media_asset(ws, "audio", "访谈", b"RIFF....WAVEfake", "talk.wav")
    with unit_of_work() as db:
        job_id = start_denoise_job(db, asset=db.get(Asset, source), created_by=None).id
    assert wait_for_idle_jobs(timeout=30)

    assert _status(job_id) == ("failed", CANCELLED_ERROR_KEY)
    assert _registered("denoised") == []


def test_a_gif_cancelled_as_it_finishes_registers_nothing(monkeypatch) -> None:
    from app.domain.assets import video_gif

    def encode_then_get_cancelled(source, target: Path, **_kwargs) -> None:
        target.write_bytes(b"GIF89a")
        _cancel_now()

    monkeypatch.setattr(video_gif, "encode_video_gif", encode_then_get_cancelled)
    ws = _workspace()
    video = _media_asset(ws, "video", "片子", b"not-a-video", "clip.mp4")
    with unit_of_work() as db:
        job_id = video_gif.start_video_to_gif(db, asset=db.get(Asset, video), created_by=None).id
    assert wait_for_idle_jobs(timeout=30)

    assert _status(job_id) == ("failed", CANCELLED_ERROR_KEY)
    with SessionLocal() as db:
        assert [one.name for one in db.scalars(select(Asset).where(Asset.name.like("%GIF%")))] == []


def test_a_remote_voice_cancelled_while_the_engine_speaks_registers_nothing(monkeypatch) -> None:
    """付费的那次合成已经回来了:账照记(不在这条测试里),产出不进素材库,任务留在「已取消」。"""
    from app.domain.voices import voices

    ws = _workspace()
    job_id = _job(ws, "tts")

    def speak_then_get_cancelled(db, *, out_dir: Path, **_kwargs) -> Path:
        out = out_dir / "speech.wav"
        out.write_bytes(b"RIFF....WAVE")
        _cancel_now()
        return out

    monkeypatch.setattr(voices, "speak_to_file", speak_then_get_cancelled)
    # 派发处给执行体设好的上下文(dispatch_job 的 run_as_job),这里直接调执行体,照样设上。
    token = jobs_bus.set_parent_job(job_id, strict=False)
    try:
        voices._run_synthesis_body(job_id, None, "你好", None, "openai", "alloy", 1.0, ws)
    except jobs_bus.JobCancelled:
        pass  # 派发处的兜底接得住它
    finally:
        jobs_bus.reset_parent_job(token)

    assert _status(job_id) == ("failed", CANCELLED_ERROR_KEY)
    assert _registered("tts") == []
