"""素材记出处(`derived_from`),「含 AI 生成内容」在登记时顺着出处继承(`ai_generated`)。

此前截一段、转 GIF、取一帧、导出成片……这些派生素材不记出处,导出时只认生成记录:AI 视频截一段再剪进
时间线,成片里就没有 AI 标识。这里每一条都走**真的入口**(画板截取的任务、转 GIF 的接口、取帧的接口、导出的
接口、插件调用),不桩掉登记那一步 —— 漏记出处的正是那一步。
"""

from __future__ import annotations

import shutil
import subprocess
import textwrap
import time
from pathlib import Path

import pytest

from app.core.db import SessionLocal
from app.db.models import Asset, PluginInstance, PluginPackage
from app.domain.assets import register_file_asset
from app.domain.assets.lineage import EXPORT, TRIM, Derivation, ai_generated_assets, derived
from tests.util import fresh_client, insert_asset, user_id

HAS_FFMPEG = shutil.which("ffmpeg") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")


def _video(path: Path, seconds: float = 2.0) -> Path:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size=320x180:rate=25:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(path)], check=True, timeout=60)
    return path


def _space(client) -> tuple[str, str]:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    return ws, project


def _register(path: Path, ws: str, project: str, name: str, *, ai: bool) -> str:
    """登记一段素材;`ai=True` 是生成任务交回的那种(见 generation.runner)。"""
    with SessionLocal() as db:
        return register_file_asset(db, workspace_id=ws, project_id=project, source_path=path, name=name,
                                   source="generated" if ai else "imported", ai_generated=ai).id


def _done(client, job_id: str, timeout: float = 90) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        assert "status" in job, job
        if job["status"] in ("succeeded", "failed"):
            assert job["status"] == "succeeded", job.get("error")
            return job
        time.sleep(0.2)
    raise AssertionError(f"任务 {job_id} 没跑完")


def _trim(client, asset_id: str) -> str:
    from app.domain.boards.trim import start_trim

    with SessionLocal() as db:
        job_id = start_trim(db, asset=db.get(Asset, asset_id), start=0.2, end=1.2, created_by=user_id()).id
        db.commit()  # 派发在提交之后起线程(见 jobs.dispatch_job)
    return _done(client, job_id)["result"]["asset_id"]


@needs_ffmpeg
def test_AI_视频截一段_再转GIF_再取一帧_每一级都记出处_含AI一路传下去(tmp_path) -> None:
    client = fresh_client()
    ws, project = _space(client)
    root = _register(_video(tmp_path / "ai.mp4"), ws, project, "AI 视频", ai=True)

    trimmed = _trim(client, root)
    gif = _done(client, client.post(f"/api/assets/{trimmed}/convert-gif", json={"width": 160}).json()["id"])["result"]["asset_id"]
    frame = client.post(f"/api/assets/{trimmed}/frame", json={"at": 0.5}).json()["id"]

    got = {one: client.get(f"/api/assets/{one}").json() for one in (trimmed, gif, frame)}
    assert got[trimmed]["derived_from"] == [{"asset_id": root, "op": "trim"}]
    assert got[gif]["derived_from"] == [{"asset_id": trimmed, "op": "gif"}]
    assert got[frame]["derived_from"] == [{"asset_id": trimmed, "op": "frame"}]
    assert all(one["ai_generated"] for one in got.values()), "AI 视频加工两道之后认不出是 AI 了"
    assert "derived_from_asset_id" not in got[gif]["media_info"], "出处只记一处,不再塞进 media_info"

    # 来源链:GIF 是从截出来的那段「转 GIF」来的,那段又是从原片「截取」来的。
    chain = client.get(f"/api/assets/{gif}/lineage").json()
    assert chain["ai_generated"] is True
    [cut] = chain["parents"]
    assert (cut["asset_id"], cut["op"], cut["name"], cut["ai_generated"]) == (trimmed, "gif", got[trimmed]["name"], True)
    assert [(one["asset_id"], one["op"], one["name"]) for one in cut["parents"]] == [(root, "trim", "AI 视频")]

    # 原片删掉:截出来的那段照样是 AI 内容;来源链上那一级写「已删除」,而不是凭空消失。
    assert client.delete(f"/api/assets/{root}").status_code == 204
    assert client.get(f"/api/assets/{gif}").json()["ai_generated"] is True
    [cut] = client.get(f"/api/assets/{gif}/lineage").json()["parents"]
    assert cut["parents"] == [{"asset_id": root, "op": "trim", "name": None, "kind": None, "ai_generated": None,
                               "parents": []}]


@needs_ffmpeg
def test_不是AI的素材加工出来也不是AI(tmp_path) -> None:
    client = fresh_client()
    ws, project = _space(client)
    shot = _register(_video(tmp_path / "shot.mp4"), ws, project, "实拍", ai=False)
    trimmed = _trim(client, shot)
    assert client.get(f"/api/assets/{trimmed}").json()["ai_generated"] is False


@needs_ffmpeg
def test_导出成片的出处是用到的素材_含AI的成片拿去再剪再导出照样认得出(tmp_path) -> None:
    client = fresh_client()
    ws, project = _space(client)
    shot = _register(_video(tmp_path / "shot.mp4"), ws, project, "实拍", ai=False)
    ai_clip = _register(_video(tmp_path / "ai.mp4"), ws, project, "AI 视频", ai=True)

    def export(*clips: tuple[str, float]) -> dict:
        sequence = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S",
                                                       "width": 320, "height": 180}).json()
        track = next(one for one in sequence["tracks"] if one["kind"] == "video")
        for asset_id, start in clips:
            client.post(f"/api/sequences/{sequence['id']}/clips",
                        json={"track_id": track["id"], "asset_id": asset_id, "timeline_start": start, "src_in": 0, "src_out": 1})
        #: 不要画面上的「AI 生成」标识:这条看的是出处,而烧标识要 libass 或浏览器那条路 —— 精简版 ffmpeg 的机器上
        #: 含 AI 的那几次会在建任务之前就被拒(见 render_executor.ensure_text_can_burn)。隐式标识照写。
        job = _done(client, client.post(f"/api/sequences/{sequence['id']}/export", json={"ai_label": False}).json()["id"])
        return client.get(f"/api/assets/{job['result']['asset_id']}").json() | {"sequence_id": sequence["id"]}

    mixed = export((shot, 0.0), (ai_clip, 1.0))
    assert mixed["derived_from"] == [{"asset_id": shot, "op": "export"}, {"asset_id": ai_clip, "op": "export"}]
    assert mixed["ai_generated"] is True

    # 时间线上取当前帧:出处是那一刻画面上的素材。
    still = client.post(f"/api/sequences/{mixed['sequence_id']}/frame", json={"at": 1.5}).json()
    assert (still["derived_from"], still["ai_generated"]) == ([{"asset_id": ai_clip, "op": "frame"}], True)
    still = client.post(f"/api/sequences/{mixed['sequence_id']}/frame", json={"at": 0.5}).json()
    assert (still["derived_from"], still["ai_generated"]) == ([{"asset_id": shot, "op": "frame"}], False)

    again = export((mixed["id"], 0.0))
    assert again["derived_from"] == [{"asset_id": mixed["id"], "op": "export"}]
    assert again["ai_generated"] is True, "导出成片再拿去剪、再导出,AI 内容认不出来了"

    plain = export((shot, 0.0))
    assert plain["ai_generated"] is False


def test_含AI的判定只读登记时定下的标记_一次查询() -> None:
    client = fresh_client()
    ws, _project = _space(client)
    plain = insert_asset(ws, kind="video", name="实拍")
    with SessionLocal() as db:
        generated = Asset(workspace_id=ws, kind="video", name="AI", ai_generated=True)
        db.add(generated)
        db.commit()
        assert ai_generated_assets(db, {plain, generated.id, ""}) == {generated.id}
        assert ai_generated_assets(db, set()) == set()


def test_出处的操作是一张封闭的表() -> None:
    """界面按 op 显示「来自:xxx(截取)」,认不出的 op 只能显示成一串英文。"""
    assert derived(TRIM, "a", "a", None, "b") == (Derivation("a", TRIM), Derivation("b", TRIM))
    assert derived(EXPORT) == ()
    with pytest.raises(ValueError):
        Derivation("a", "squash")


PROCESSOR = {
    "id": "processor",
    "name": "加工器",
    "version": "0.1.0",
    "runtime": {"kind": "process", "entry": "main.py"},
    "tools": {"expose": "all", "declare": [{
        "name": "process",
        "description": "把一份素材加工成新的一份",
        "input_schema": {"type": "object", "properties": {"asset_id": {"type": "string", "format": "asset"}},
                         "required": ["asset_id"]},
    }]},
}
PROCESSOR_ENTRY = """
    import json, os, shutil, sys
    request = json.loads(sys.stdin.read())
    out = os.path.join(os.environ["MOSAEL_PLUGIN_OUTPUT_DIR"], "processed.txt")
    shutil.copyfile(request["input"]["asset_id"], out)
    print(json.dumps({"ok": True, "output": {"artifact": {"path": "processed.txt"}}}))
"""


def test_插件拿AI素材加工出来的_记着交给它的那份_也含AI(tmp_path) -> None:
    from app.domain.plugins.tools import invoke

    client = fresh_client()
    ws, project = _space(client)
    plugin_dir = tmp_path / "p"
    plugin_dir.mkdir()
    (plugin_dir / "main.py").write_text(textwrap.dedent(PROCESSOR_ENTRY), encoding="utf-8")
    source = tmp_path / "稿子.txt"
    source.write_text("AI 写的", encoding="utf-8")
    given = _register(source, ws, project, "稿子", ai=True)
    with SessionLocal() as db:
        package = PluginPackage(id="processor", name="加工器", version="0.1.0", manifest={**PROCESSOR, "_path": str(plugin_dir)})
        db.add(package)
        db.flush()
        instance = PluginInstance(package_id=package.id, name="加工器", enabled=True, owner_user_id="")
        db.add(instance)
        db.commit()
        invocation = invoke(db, instance.id, "process", {"asset_id": given}, workspace_id=ws)
        assert invocation.status == "succeeded", invocation.error
        made = db.get(Asset, invocation.output["asset_id"])
        assert made.derived_from == [{"asset_id": given, "op": "plugin"}]
        assert made.ai_generated is True
