"""插件可以是生成供应商(ADR 0020):一个假插件走完整条路。

钉住的是**框架**,不是 ComfyUI(那个在 test_comfyui_plugin*.py):

- 清单规矩:只给进程形态、必须有且只有一个工具认领、认领它的工具只给宿主调、预算按能力给;
- 目录 → 连接 + 模型行:插件的模型出现在 `/generation/options` 里,描述符是插件说的那一份,
  只有**他自己的**实例提供的模型才列出来;
- 一次生成走的是普通的生成执行器:输入素材拷一份交给插件、产出登记成素材、回执落库、用量记账;
- 进度、取消(取消文件)、超时(先请它停、再杀)、重启后接着取(不再提交);
- 目录刷不出来记下原因、不丢旧模型;实例删掉,连接和模型跟着走;插件连接在设置页改不了。
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import (
    Asset,
    GeneratedAsset,
    GenerationJob,
    Job,
    PluginInstance,
    PluginInvocation,
    PluginPackage,
    ProviderModel,
    ProviderProfile,
    ProviderUsageEvent,
)
from app.domain.plugins import runtime
from app.domain.plugins.manifest import ManifestError, parse
from tests.util import fresh_client, second_client, wait_status

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    b"\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)

PACKAGE_ID = "test.gen"
VENDOR = f"plugin:{PACKAGE_ID}"

MODELS: list[dict[str, Any]] = [
    {
        "id": "flows/portrait.json",
        "label": {"zh": "人像", "en": "Portrait"},
        "kind": "image",
        "modes": ["text-to-image", "image-to-image"],
        "parameters": {
            "seed": {"type": "integer"},
            "negative_prompt": {"type": "string"},
            "size": {"type": "string", "enum": ["512x512", "1024x1024"], "default": "1024x1024"},
            "3.steps": {"type": "integer", "title": "KSampler · steps", "default": 20, "minimum": 1, "maximum": 150},
            "3.sampler_name": {"type": "string", "enum": ["euler", "dpmpp_2m"], "default": "euler", "x-advanced": True},
        },
        "inputs": [{"role": "reference_image", "max": 2}],
        "prompt_dialect": "sd-tags",
    },
    {"id": "clip.json", "label": "clip", "kind": "video", "parameters": {"4.length": {"type": "integer", "default": 81}}},
    # 音频模型(ADR 0022):歌词、纯音乐是宿主有控件的词汇,时长走宿主的时长控件。
    {
        "id": "song",
        "label": "song",
        "kind": "audio",
        "modes": ["text-to-music", "lyrics-to-song"],
        "parameters": {
            "lyrics": {"type": "string", "x-multiline": True},
            "instrumental": {"type": "boolean", "default": False},
            "duration_seconds": {"type": "integer", "minimum": 5, "maximum": 60},
        },
    },
    {"bad": True},
    {"id": "", "kind": "image"},
]

PLUGIN = r'''
import base64, json, os, sys, time
from pathlib import Path

PNG = base64.b64decode("__PNG__")
MODELS = json.loads(__MODELS__)
request = json.loads(sys.stdin.read())
payload = request["input"]
data = Path(os.environ["MOSAEL_PLUGIN_DATA_DIR"])


def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


if payload.get("op") == "models":
    if os.environ.get("SERVER") == "down":
        emit({"ok": False, "error": "连不上服务器"})
    else:
        emit({"ok": True, "output": {"models": MODELS}})
    sys.exit(0)

cancel = Path(os.environ["MOSAEL_PLUGIN_CANCEL_FILE"])
inputs = payload.get("inputs") or []
with (data / "requests.jsonl").open("a", encoding="utf-8") as log:
    log.write(json.dumps({
        "input": payload,
        "input_bytes": [Path(one["path"]).read_bytes().hex() for one in inputs],
        "output_dir": os.environ.get("MOSAEL_PLUGIN_OUTPUT_DIR"),
    }) + "\n")
if payload.get("resume") is None:
    emit({"event": "task", "task": {"job": "t-1", "server": os.environ.get("SERVER")}})
emit({"event": "progress", "progress": 0.5, "message": "一半了"})
print("a stray log line that is not json", flush=True)
prompt = payload["prompt"]
if prompt == "cancel-me":
    while not cancel.exists():
        time.sleep(0.05)
    (data / "cancelled").write_text("yes")
    emit({"ok": False, "error": "interrupted"})
    sys.exit(0)
if prompt == "ignore-cancel":
    time.sleep(60)
if payload.get("kind") == "audio":
    # 一秒钟的静音 wav —— 宿主要能按音频登记它(探测时长、画波形)。
    import wave
    out = Path(os.environ["MOSAEL_PLUGIN_OUTPUT_DIR"]) / "song.wav"
    with wave.open(str(out), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 8000)
    emit({"ok": True, "output": {"outputs": [{"path": "song.wav"}], "raw": {"job": "t-1"}}})
    sys.exit(0)
out = Path(os.environ["MOSAEL_PLUGIN_OUTPUT_DIR"]) / "out.png"
out.write_bytes(Path(inputs[0]["path"]).read_bytes() if inputs else PNG)
emit({"ok": True, "output": {"outputs": [{"path": "out.png"}], "usage": {"images": 1}, "raw": {"job": "t-1"}}})
'''


def _manifest(path: Path) -> dict[str, Any]:
    return {
        "id": PACKAGE_ID,
        "name": "测试生成",
        "version": "1.0.0",
        "manifest_version": 1,
        "runtime": {"kind": "process", "entry": "main.py"},
        "provides": ["generation"],
        "permissions": ["network:test"],
        "instance": {
            "multiple": True,
            "name_template": "测试生成 · {SERVER}",
            "config": [{"key": "SERVER", "label": "服务器", "type": "string", "required": True}],
        },
        "tools": {
            "declare": [
                {"name": "gen", "provides": ["generation"], "timeout_seconds": 60, "input_schema": {"type": "object"}},
                {"name": "ping", "description": "普通工具", "input_schema": {"type": "object"}},
            ]
        },
        "_path": str(path),
    }


def _write_plugin(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    source = PLUGIN.replace("__PNG__", base64.b64encode(PNG).decode()).replace("__MODELS__", repr(json.dumps(MODELS)))
    (path / "main.py").write_text(source, encoding="utf-8")


def _connect(client, *, server: str = "alpha") -> str:
    """建一个实例、授权、启用 —— 用户在插件页走的那三步。返回实例 id。"""
    created = client.post(f"/api/plugins/{PACKAGE_ID}/instances", json={"config": {"SERVER": server}})
    assert created.status_code == 200, created.text
    instance_id = created.json()["id"]
    granted = client.patch(f"/api/plugins/instances/{instance_id}/permissions", json={"grants": {"network:test": True}})
    assert granted.status_code == 200, granted.text
    enabled = client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True})
    assert enabled.status_code == 200, enabled.text
    return instance_id


@pytest.fixture
def plugged(tmp_path: Path):
    client = fresh_client()
    _write_plugin(tmp_path / "plugin")
    with SessionLocal() as db:
        db.add(PluginPackage(id=PACKAGE_ID, name="测试生成", version="1.0.0", manifest=_manifest(tmp_path / "plugin")))
        db.commit()
    instance_id = _connect(client)
    return client, instance_id


def _options(client, kind: str) -> list[dict[str, Any]]:
    response = client.get(f"/api/generation/options?kind={kind}")
    assert response.status_code == 200, response.text
    return [one for one in response.json() if one["provider"] == VENDOR]


def _profile_id(instance_id: str) -> str:
    with SessionLocal() as db:
        return db.scalar(select(ProviderProfile.id).where(ProviderProfile.plugin_instance_id == instance_id))


def _image_asset(client, workspace: str) -> str:
    response = client.post(
        "/api/assets/import", data={"workspace_id": workspace}, files={"file": ("参考.png", PNG, "image/png")}
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _requests(tmp_path_data: Path) -> list[dict[str, Any]]:
    log = tmp_path_data / "requests.jsonl"
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


def _data_dir() -> Path:
    return runtime.data_dir_for(PACKAGE_ID)


def _submit(client, workspace: str, instance_id: str, prompt: str, **extra: Any):
    return client.post(
        "/api/generation/jobs",
        json={
            "workspace_id": workspace,
            "session_id": None,
            "project_id": None,
            "provider_profile_id": _profile_id(instance_id),
            "provider": VENDOR,
            "model": "flows/portrait.json",
            "kind": "image",
            "prompt": prompt,
            "negative_prompt": "",
            "parameters": extra.pop("parameters", {}),
            "source_assets": extra.pop("source_assets", []),
        },
    )


@pytest.fixture(autouse=True)
def _clean_plugin_data():
    import shutil

    shutil.rmtree(_data_dir(), ignore_errors=True)
    yield
    shutil.rmtree(_data_dir(), ignore_errors=True)


# --- 清单 -------------------------------------------------------------------


def _raw(**changes: Any) -> dict[str, Any]:
    raw = _manifest(Path("/tmp/x"))
    raw.pop("_path")
    raw.update(changes)
    return raw


def test_生成能力只给进程形态() -> None:
    with pytest.raises(ManifestError, match="generation"):
        parse(_raw(runtime={"kind": "mcp", "transport": "http", "url": "https://example.com/mcp"}), "m.json")


def test_生成能力必须有工具认领_而且只能有一个() -> None:
    with pytest.raises(ManifestError, match="generation"):
        parse(_raw(tools={"declare": [{"name": "gen", "input_schema": {"type": "object"}}]}), "m.json")
    twice = {"declare": [
        {"name": "a", "provides": ["generation"], "input_schema": {"type": "object"}},
        {"name": "b", "provides": ["generation"], "input_schema": {"type": "object"}},
    ]}
    with pytest.raises(ManifestError, match="a, b"):
        parse(_raw(tools=twice), "m.json")


def test_认领生成的工具只给宿主调_预算按能力给(plugged) -> None:
    """它说的是流式协议;让智能体直接调它,等于绕开生成任务、用量和回执。"""
    client, instance_id = plugged
    from app.domain.plugins import tools

    with SessionLocal() as db:
        instance = db.get(PluginInstance, instance_id)
        by_name = {tool["name"]: tool for tool in tools.all_tools(db, instance)}
        assert by_name["gen"]["internal"] is True and by_name["gen"]["provides"] == ["generation"]
        assert by_name["ping"]["internal"] is False
        # 声明了 60 秒就是 60 秒;普通工具的 1800 秒上限不管它,生成工具的上限是 6 小时。
        assert by_name["gen"]["timeout_seconds"] == 60
        assert "gen" not in {tool["name"] for tool in tools.exposed(db, None)}
    page = client.get("/api/plugins").json()
    package = next(one for one in page if one["id"] == PACKAGE_ID)
    assert package["provides"] == ["generation"]
    assert [tool["name"] for tool in package["instances"][0]["tools"]] == ["ping"]


def test_生成工具不写预算是一小时_上限六小时() -> None:
    from app.domain.plugins.tools import _declared_timeout

    assert _declared_timeout({"provides": ["generation"]}) == 3600
    assert _declared_timeout({"provides": ["generation"], "timeout_seconds": 99999}) == 6 * 3600
    assert _declared_timeout({"timeout_seconds": 99999}) == 1800


# --- 目录 → 选择器 -----------------------------------------------------------


def test_接上之后_插件的模型出现在选择器里(plugged) -> None:
    client, instance_id = plugged
    images = _options(client, "image")
    assert [one["model"] for one in images] == ["flows/portrait.json"]
    portrait = images[0]
    assert portrait["label"] == "测试生成 · alpha · 人像"
    assert portrait["adapter_available"] is True and portrait["capabilities_known"] is True
    caps = portrait["capabilities"]
    assert caps["parameter_keys"] == [
        "seed", "negative_prompt", "size", "3.steps", "3.sampler_name", "reference_image"
    ]
    assert caps["sizes"] == ["512x512", "1024x1024"] and caps["default_size"] == "1024x1024"
    assert caps["source_limits"] == {"reference_image": 2}
    assert caps["modes"] == ["text-to-image", "image-to-image"]
    assert caps["prompt_dialect"] == "sd-tags"
    # 宿主词汇以外的键进 parameter_schema,带着插件给的名字、范围、默认值
    assert caps["parameter_schema"]["3.steps"] == {
        "type": "integer", "title": "KSampler · steps", "default": 20, "minimum": 1, "maximum": 150
    }
    assert caps["parameter_schema"]["3.sampler_name"]["x-advanced"] is True
    assert "seed" not in caps["parameter_schema"] and "size" not in caps["parameter_schema"]
    # 视频、音频照样进(音频是生成的第三种,ADR 0022);坏条目丢掉
    assert [one["model"] for one in _options(client, "video")] == ["clip.json"]
    [song] = _options(client, "audio")
    assert song["model"] == "song" and song["adapter_available"] is True
    song_caps = song["capabilities"]
    assert song_caps["parameter_keys"] == ["lyrics", "instrumental", "duration_seconds"]
    # 歌词、纯音乐用宿主的控件(不进 parameter_schema);纯音乐是个布尔开关,默认值照插件说的
    assert "parameter_schema" not in song_caps
    assert song_caps["boolean_parameters"] == ["instrumental"] and song_caps["default_instrumental"] is False
    assert song_caps["min_duration_seconds"] == 5 and song_caps["max_duration_seconds"] == 60
    assert song_caps["modes"] == ["text-to-music", "lyrics-to-song"]
    status = client.get("/api/plugins").json()
    instance = next(one for one in status if one["id"] == PACKAGE_ID)["instances"][0]
    assert instance["capability_status"]["generation"]["models"] == 3
    assert instance["capability_status"]["generation"]["error"] == ""


def test_别人看不见我的插件模型(plugged) -> None:
    other = second_client("other")
    assert _options(other, "image") == []


def test_停用了就不在选择器里(plugged) -> None:
    client, instance_id = plugged
    client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": False})
    assert _options(client, "image") == []


def test_目录刷不出来_记下原因且不丢已有的模型(plugged) -> None:
    client, instance_id = plugged
    changed = client.patch(f"/api/plugins/instances/{instance_id}", json={"config": {"SERVER": "down"}})
    assert changed.status_code == 200, changed.text
    status = changed.json()["capability_status"]["generation"]
    assert "连不上服务器" in status["error"]
    assert status["models"] == 3, "上一次成功的数不该被失败抹掉"
    # ComfyUI 没开不等于它的工作流都没了:模型还在
    assert [one["model"] for one in _options(client, "image")] == ["flows/portrait.json"]


def test_实例删掉_连接和模型跟着走(plugged) -> None:
    client, instance_id = plugged
    profile_id = _profile_id(instance_id)
    assert client.delete(f"/api/plugins/instances/{instance_id}").status_code == 204
    with SessionLocal() as db:
        assert db.get(ProviderProfile, profile_id) is None
        assert db.scalars(select(ProviderModel).where(ProviderModel.provider_profile_id == profile_id)).all() == []
    assert _options(client, "image") == []


def test_插件连接在设置页只读(plugged) -> None:
    client, instance_id = plugged
    profile_id = _profile_id(instance_id)
    listed = next(one for one in client.get("/api/settings/providers").json() if one["id"] == profile_id)
    assert listed["plugin_instance_id"] == instance_id and listed["plugin_package_id"] == PACKAGE_ID
    assert client.patch(f"/api/settings/providers/{profile_id}", json={"name": "改名"}).status_code == 403
    assert client.delete(f"/api/settings/providers/{profile_id}").status_code == 403
    assert client.post(f"/api/settings/providers/{profile_id}/models", json={"id": "x"}).status_code == 403
    # 但它的模型可以当默认模型
    default = client.put(
        "/api/settings/provider-defaults/image",
        json={"provider_profile_id": profile_id, "model": "flows/portrait.json"},
    )
    assert default.status_code == 200, default.text


# --- 一次生成 ----------------------------------------------------------------


def test_一次生成走普通的生成执行器(plugged) -> None:
    client, instance_id = plugged
    workspace = client.post("/api/workspaces", json={"name": "生成"}).json()["id"]
    reference = _image_asset(client, workspace)
    submitted = _submit(
        client, workspace, instance_id, "一只猫",
        parameters={"seed": 7, "3.steps": 30},
        source_assets=[{"asset_id": reference, "role": "reference_image"}],
    )
    assert submitted.status_code == 200, submitted.text
    job_id = submitted.json()["job"]["id"]
    assert wait_status(client, job_id, timeout=30) == "succeeded"

    [request] = _requests(_data_dir())
    sent = request["input"]
    assert sent["op"] == "generate" and sent["model"] == "flows/portrait.json" and sent["kind"] == "image"
    assert sent["parameters"] == {"seed": 7, "3.steps": 30}
    # 输入素材是**一份拷贝**,落在这次调用的暂存目录里,不是素材库里那一份
    [given] = sent["inputs"]
    assert given["role"] == "reference_image"
    assert Path(given["path"]).parent.parent == Path(request["output_dir"])
    assert bytes.fromhex(request["input_bytes"][0]) == PNG
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        # 回执在对面交回的那一刻落进了和远端任务同一格(ADR 0019)
        assert json.loads(job.payload["remote_task"]["poll_path"]) == {"job": "t-1", "server": "alpha"}
        assert job.progress == 1.0
        [asset_id] = job.result["asset_ids"]
        produced = db.get(GeneratedAsset, asset_id)
        assert produced.provider == VENDOR and produced.model == "flows/portrait.json"
        usage = db.scalars(select(ProviderUsageEvent).where(ProviderUsageEvent.job_id == job_id)).one()
        assert usage.provider == VENDOR and usage.provider_profile_id == _profile_id(instance_id)
        assert usage.units["images"] == 1
        invocation = db.scalars(
            select(PluginInvocation).where(PluginInvocation.instance_id == instance_id, PluginInvocation.tool_name == "gen")
            .order_by(PluginInvocation.created_at.desc())
        ).first()
        assert invocation.status == "succeeded"
        assert invocation.input["inputs"] == ["reference_image"], "调用记录里不留一次性的暂存路径"


def test_插件的音频模型走同一个生成执行器_产出登记成音频素材(plugged) -> None:
    """音频是生成的第三种(ADR 0022):插件声明一个 kind=audio 的模型,就和图像一样经普通的
    生成执行器跑完 —— 产出按**音频**进素材库(时长在 media_info 里),用量按「首」和探测到的
    真实秒数记。"""
    client, instance_id = plugged
    workspace = client.post("/api/workspaces", json={"name": "生成"}).json()["id"]
    response = client.post(
        "/api/generation/jobs",
        json={
            "workspace_id": workspace,
            "provider_profile_id": _profile_id(instance_id),
            "provider": VENDOR,
            "model": "song",
            "kind": "audio",
            "prompt": "",
            "parameters": {"lyrics": "[Verse]\n啦啦啦", "instrumental": False},
        },
    )
    assert response.status_code == 200, response.text
    job_id = response.json()["job"]["id"]
    assert wait_status(client, job_id, timeout=30) == "succeeded"
    [request] = _requests(_data_dir())
    sent = request["input"]
    assert sent["kind"] == "audio" and sent["parameters"] == {"lyrics": "[Verse]\n啦啦啦", "instrumental": False}
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        [asset_id] = job.result["asset_ids"]
        asset = db.get(Asset, asset_id)
        assert asset.kind == "audio"
        assert asset.media_info["duration"] == pytest.approx(1.0, abs=0.05)
        usage = db.scalars(select(ProviderUsageEvent).where(ProviderUsageEvent.job_id == job_id)).one()
        assert usage.capability == "audio"
        assert usage.units["audios"] == 1
        assert usage.units["audio_seconds"] == pytest.approx(1.0, abs=0.05)
        assert usage.units["lyrics_characters"] == len("[Verse]\n啦啦啦")


def test_插件的音频模型_纯音乐和歌词不能同时给(plugged) -> None:
    client, instance_id = plugged
    workspace = client.post("/api/workspaces", json={"name": "生成"}).json()["id"]
    response = client.post(
        "/api/generation/jobs",
        json={
            "workspace_id": workspace,
            "provider_profile_id": _profile_id(instance_id),
            "provider": VENDOR,
            "model": "song",
            "kind": "audio",
            "prompt": "钢琴",
            "parameters": {"lyrics": "啦啦啦", "instrumental": True},
        },
    )
    assert response.status_code == 422
    assert "纯音乐" in response.json()["detail"]


def test_参数按插件的声明校验(plugged) -> None:
    client, instance_id = plugged
    workspace = client.post("/api/workspaces", json={"name": "生成"}).json()["id"]
    rejected = _submit(client, workspace, instance_id, "一只猫", parameters={"3.steps": 500})
    assert rejected.status_code == 422
    assert "KSampler · steps" in rejected.json()["detail"] and "150" in rejected.json()["detail"]
    rejected = _submit(client, workspace, instance_id, "一只猫", parameters={"3.sampler_name": "lms"})
    assert rejected.status_code == 422 and "euler" in rejected.json()["detail"]


def test_取消经取消文件传到插件(plugged) -> None:
    client, instance_id = plugged
    workspace = client.post("/api/workspaces", json={"name": "生成"}).json()["id"]
    job_id = _submit(client, workspace, instance_id, "cancel-me").json()["job"]["id"]
    deadline = time.monotonic() + 20
    while not _requests(_data_dir()) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 200
    deadline = time.monotonic() + 20
    while not (_data_dir() / "cancelled").exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert (_data_dir() / "cancelled").exists(), "插件没收到取消 —— 远端的活就停不下来"
    from app.domain.jobs import wait_for_idle_jobs

    wait_for_idle_jobs(timeout=20)
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        # 取消是一种失败终态(见 jobs._cancel_job_row),原因说的是「已取消」而不是插件出错
        assert job.status == "failed" and job.error_key == "jobErr_cancelled"
        assert not db.scalars(select(GeneratedAsset).where(GeneratedAsset.job_id == job_id)).all()


def test_重启后接着取_不再提交(plugged, monkeypatch: pytest.MonkeyPatch) -> None:
    client, instance_id = plugged
    workspace = client.post("/api/workspaces", json={"name": "生成"}).json()["id"]
    monkeypatch.setattr("app.api.routes.generation.start_generation_thread", lambda _generation_id: None)
    job_id = _submit(client, workspace, instance_id, "一只猫").json()["job"]["id"]
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        # 上一个进程提交过、记下了回执,然后后端重启了
        job.status = "running"
        job.payload = {**job.payload, "remote_task": {"poll_path": json.dumps({"job": "t-9"})}}
        db.commit()
    from app.domain.generation.runner import resume_generation

    assert resume_generation(job_id) is True
    assert wait_status(client, job_id, timeout=30) == "succeeded"
    [request] = _requests(_data_dir())
    assert request["input"]["resume"] == {"job": "t-9"}
    with SessionLocal() as db:
        # 接着取的那一次没有再交回新回执(插件只在提交时交),回执还是原来那张
        assert json.loads(db.get(Job, job_id).payload["remote_task"]["poll_path"]) == {"job": "t-9"}
        assert db.scalars(select(GenerationJob).where(GenerationJob.job_id == job_id)).one().result_asset_id


# --- 流式运行时 --------------------------------------------------------------


def _stream(tmp_path: Path, script: str, *, timeout: float, cancelled=lambda: False):
    plugin = tmp_path / "stream"
    plugin.mkdir()
    (plugin / "main.py").write_text(script, encoding="utf-8")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    progress: list[tuple[float, str]] = []
    tasks: list[dict[str, Any]] = []
    hooks = runtime.StreamHooks(on_progress=lambda f, m: progress.append((f, m)), on_task=tasks.append, is_cancelled=cancelled)
    result = None
    error: Exception | None = None
    try:
        result = runtime.stream_tool(plugin, "main.py", "gen", {"op": "generate"}, hooks=hooks, scratch_dir=scratch, timeout=timeout)
    except runtime.PluginRuntimeError as exc:
        error = exc
    return result, error, progress, tasks


def test_提示词优化按模型自己说的写法(plugged) -> None:
    """同一个 ComfyUI 上 SD 1.5 的图吃标签、Flux 的图吃自然语言 —— 写法跟着模型走,不跟 vendor。"""
    from app.domain.generation.prompt_optimizer import _dialect_of, guide_for
    from tests.util import user_id

    with SessionLocal() as db:
        assert _dialect_of(db, user_id(), VENDOR, "flows/portrait.json") == "sd-tags"
        assert _dialect_of(db, user_id(), VENDOR, "不存在.json") == ""
    tags = guide_for(VENDOR, "flows/portrait.json", "sd-tags")
    assert tags.wants_negative is True and tags.prompt_lang == "en"
    assert guide_for(VENDOR, "clip.json").label == "通用"


def test_流式_进度与回执回到调用线程_非JSON行跳过(tmp_path: Path) -> None:
    script = (
        "import json, sys\nsys.stdin.read()\n"
        "print(json.dumps({'event': 'progress', 'progress': 1.7, 'message': 'x' * 500}), flush=True)\n"
        "print('log line', flush=True)\n"
        "print(json.dumps({'event': 'task', 'task': {'id': 1}}), flush=True)\n"
        "print(json.dumps({'ok': True, 'output': {'outputs': []}}), flush=True)\n"
    )
    result, error, progress, tasks = _stream(tmp_path, script, timeout=20)
    assert error is None and result is not None and result.output == {"outputs": []}
    assert progress == [(1.0, "x" * 200)], "比例夹在 0..1,话截到 200 字"
    assert tasks == [{"id": 1}]


def test_流式_超时先请插件停_不停再杀(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime, "CANCEL_GRACE_SECONDS", 0.5)
    polite = (
        "import json, os, sys, time\nsys.stdin.read()\nfrom pathlib import Path\n"
        "cancel = Path(os.environ['MOSAEL_PLUGIN_CANCEL_FILE'])\n"
        "while not cancel.exists():\n    time.sleep(0.02)\n"
        "Path(os.environ['MOSAEL_PLUGIN_OUTPUT_DIR'], 'saw-cancel').write_text('1')\n"
        "print(json.dumps({'ok': False, 'error': 'stopped'}), flush=True)\n"
    )
    started = time.monotonic()
    _, error, _, _ = _stream(tmp_path, polite, timeout=0.5)
    assert isinstance(error, runtime.PluginTimeout)
    assert (tmp_path / "scratch" / "saw-cancel").exists(), "超时不是直接杀:远端还在跑时,只有插件知道怎么让它停"
    assert time.monotonic() - started < 10

    stubborn = "import sys, time\nsys.stdin.read()\ntime.sleep(60)\n"
    started = time.monotonic()
    other = tmp_path / "other"
    other.mkdir()
    _, error, _, _ = _stream(other, stubborn, timeout=0.3)
    assert isinstance(error, runtime.PluginTimeout)
    assert time.monotonic() - started < 15, "不理取消文件的插件在宽限之后被杀掉"


def test_流式_用户取消(tmp_path: Path) -> None:
    script = (
        "import json, os, sys, time\nsys.stdin.read()\nfrom pathlib import Path\n"
        "cancel = Path(os.environ['MOSAEL_PLUGIN_CANCEL_FILE'])\n"
        "while not cancel.exists():\n    time.sleep(0.02)\n"
        "print(json.dumps({'ok': False, 'error': 'interrupted'}), flush=True)\n"
    )
    _, error, _, _ = _stream(tmp_path, script, timeout=30, cancelled=lambda: True)
    assert isinstance(error, runtime.PluginCancelled)


def test_流式_没给结果就退出要说清楚(tmp_path: Path) -> None:
    _, error, _, _ = _stream(tmp_path, "import sys\nsys.stdin.read()\nprint('hi')\n", timeout=20)
    assert error is not None and "ok" in str(error)


def test_插件跑着的时候不攥着数据库连接(plugged, monkeypatch: pytest.MonkeyPatch) -> None:
    """一次插件生成一跑就是几十分钟到几小时。此前流式那条不经过「先交还连接」那一步:
    每次生成都攥着一条连接和一个没结束的读事务直到跑完 —— 连接池被几次生成占满,
    SQLite 的 WAL 因为一直有读者而回卷不了。一问一答那条早就先交还了,两条该是一个规矩。"""
    from app.domain.plugins import tools
    from app.domain.plugins.runtime import StreamHooks, ToolResult

    _, instance_id = plugged
    seen: list[bool] = []

    with SessionLocal() as db:
        def fake_run(*args: Any, **kwargs: Any) -> ToolResult:
            seen.append(db.in_transaction())
            return ToolResult(output={"models": []})

        monkeypatch.setattr(tools, "stream_tool", fake_run)
        monkeypatch.setattr(tools, "execute_tool", fake_run)
        hooks = StreamHooks(on_progress=lambda *_: None, on_task=lambda _t: None, is_cancelled=lambda: False)
        tools.invoke_host(db, instance_id, "generation", {"op": "generate"}, hooks=hooks)
        tools.invoke_host(db, instance_id, "generation", {"op": "models"})
    assert seen == [False, False], "插件进程跑着的时候,会话还攥着一个读事务"
