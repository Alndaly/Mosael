"""本机服务的宿主那一层(ADR 0041 §2):一个声明了 `services` 的测试插件,它的 `service_launch` 让宿主起
tests/fake_local_service.py 那个假服务。走一遍:

- 建:要部署管理员、要确认过「会在这台机器上运行这个目录里的代码」;端口从起点往上找第一个空的(没人在听、没分给别的
  连接),写进连接的 `server_url`;
- 起 / 停 / 状态 / 日志的接口;认目录、补装要确认;普通成员只能看、只能「用到时起」;
- **用到时起**:智能体、工作流调这个连接的工具,停着就先起、等它就绪,插件的环境里带着 MOSAEL_LOCAL_SERVICE;任务里
  报一句「正在启动本机 …」;后台问指纹不替它起;
- 同一个目录只起一份、端口被占说清楚;改端口要先停,改完插件把按旧地址存的数据搬过去;
- 后端重启:对得上的接回来当作运行中,对不上的不碰;「保持运行」的跟着起;退出时全部停;连接删了先停;
- 工作流库的「重启」:插件说这台归宿主管(`host_restart`),宿主停了再起。
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from app.core.child_process import process_alive
from app.core.db import SessionLocal
from app.db.models import LocalService, PluginInstance, PluginPackage
from app.domain import local_services
from app.domain.local_services import pidfiles, records, supervisor
from app.domain.plugins import tools
from app.domain.plugins.errors import PluginDomainError
from tests.util import first_free_port_of_this_worker, fresh_client, second_client

FAKE = Path(__file__).resolve().parent / "fake_local_service.py"
PACKAGE_ID = "dev.test.localsvc"

#: 测试插件:`svc` 回答本机服务的那几个操作(起的是假服务,参数从所选目录里的 fake.json 读);`ping` 是个普通工具,
#: 交回它看到的环境 —— 用来验「用到时起」和那个告诉插件「这台归宿主管」的变量。
PLUGIN = r'''
import json, os, sys
from pathlib import Path

FAKE = __FAKE__

def options(directory):
    path = Path(directory) / "fake.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}

def svc(payload):
    op = payload.get("op")
    directory = str(payload.get("directory") or "")
    if op == "service_detect":
        if not Path(directory).is_dir():
            return {"ok": False, "problems": [{"level": "error", "text": {"zh": "没有这个目录", "en": "No such folder"}}]}
        return {"ok": True, "facts": [{"label": {"zh": "版本", "en": "Version"}, "value": "0.0.0-fake"},
                                      {"label": "", "value": "没有名字的不摆"}],
                "problems": [{"level": "warning", "text": {"zh": "少了点东西", "en": "Something is missing"}}],
                "add_nodes": {"title": {"zh": "补装", "en": "Add it"}, "description": "装进 custom_nodes"}}
    if op == "service_busy":
        control = Path(os.environ["MOSAEL_PLUGIN_DATA_DIR"]) / "busy.json"
        said = json.loads(control.read_text(encoding="utf-8")) if control.is_file() else {"busy": False}
        if said.get("fail"):
            raise RuntimeError("问不到它的队列")
        return {"busy": said.get("busy", False)}
    if op == "service_model_folders":
        found = []
        for path in payload.get("shared_models") or []:
            ok = Path(path).is_dir() and (Path(path).name == "models" or "kept-models" in path)
            found.append({"path": path, "ok": ok, "layout": {"zh": "模型文件夹", "en": "Models folder"} if ok else "",
                          "folders": ["checkpoints"] if ok else [], "loaded": None, "models": None,
                          "problem": "" if ok else {"zh": f"认不出:{path}", "en": f"Not recognized: {path}"}})
        return {"folders": found, "running": False}
    if op == "service_launch":
        (Path(directory) / "launch.json").write_text(json.dumps(payload), encoding="utf-8") if Path(directory).is_dir() else None
        flags = options(directory).get("flags", [])
        argv = [sys.executable, FAKE, "--port", str(payload["port"]),
                "--listen", "0.0.0.0" if payload.get("listen_lan") else "127.0.0.1", *flags, *payload.get("extra_args", [])]
        return {"argv": argv, "env": {"FAKE_ENV": "插件给的", "MOSAEL_SNEAKY": "x", "HTTPS_PROXY": "http://plugin.invalid"},
                "cwd": directory, "health_path": "/system_stats", "ready_timeout": options(directory).get("ready", 20)}
    if op == "service_add_nodes":
        target = Path(directory) / "custom_nodes" / "extra"
        target.mkdir(parents=True, exist_ok=True)
        return {"installed": ["extra"], "path": str(target), "message": {"zh": "装好了", "en": "Installed"}}
    if op == "service_discover":
        return {"servers": [{"url": "http://127.0.0.1:8188", "label": {"zh": "本机的那台", "en": "The local one"}},
                            {"url": "http://192.168.1.2:8188", "label": "别的机器上的不算本机"}]}
    if op == "service_readdress":
        root = Path(os.environ["MOSAEL_PLUGIN_DATA_DIR"])
        (root / "readdress.json").write_text(json.dumps({"from": payload["from"], "to": payload["to"]}), encoding="utf-8")
        return {"moved": 1}
    raise ValueError(op)

def ping(payload):
    return {"service": os.environ.get("MOSAEL_LOCAL_SERVICE", ""), "server": os.environ.get("SERVER_URL", ""),
            "shared": os.environ.get("MOSAEL_LOCAL_SERVICE_SHARED", "")}

def reach(payload):
    # 像 ComfyUI 插件那样问一下服务器;连不上就说插件自己那句(只适合「连一台服务器」)
    import urllib.request
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                os.environ.get("SERVER_URL", "") + "/system_stats", timeout=1) as response:
            return {"status": response.status}
    except Exception:
        raise RuntimeError("连不上这台服务器,确认它在运行、地址填对")

def boom(payload):
    raise RuntimeError("这张工作流本身坏了")

def slow(payload):
    import time
    time.sleep(0.4)  # 像一次要跑一会儿的生成
    return {"done": True}

request = json.loads(sys.stdin.read())
handler = {"svc": svc, "ping": ping, "reach": reach, "boom": boom, "slow": slow}[request["tool"]]
try:
    json.dump({"ok": True, "output": handler(request.get("input") or {})}, sys.stdout, ensure_ascii=False)
except Exception as exc:
    json.dump({"ok": False, "error": str(exc)}, sys.stdout, ensure_ascii=False)
'''


def _manifest(path: Path) -> dict[str, Any]:
    return {
        "id": PACKAGE_ID, "name": "本机服务测试", "version": "1.0.0", "manifest_version": 8,
        "runtime": {"kind": "process", "entry": "main.py"},
        "instance": {
            "multiple": True,
            "config": [{"key": "server_url", "label": "地址", "type": "string", "required": True,
                        "default": "http://127.0.0.1:8188"}],
        },
        "tools": {
            "expose": "all",
            "declare": [
                {"name": "svc", "internal": True, "input_schema": {"type": "object"}},
                {"name": "ping", "effects": "none", "input_schema": {"type": "object"}},
                {"name": "reach", "effects": "none", "input_schema": {"type": "object"}},
                {"name": "boom", "effects": "none", "input_schema": {"type": "object"}},
                {"name": "slow", "effects": "none", "input_schema": {"type": "object"}},
            ],
        },
        "services": [{"key": "fake", "title": {"zh": "假服务", "en": "Fake service"}, "tool": "svc"}],
        "_path": str(path),
    }


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(supervisor, "HEALTH_POLL_SECONDS", 0.05)
    monkeypatch.setattr(supervisor, "WATCH_SECONDS", 0.05)
    monkeypatch.setattr(supervisor, "RESTART_BASE_DELAY", 0.1)
    monkeypatch.setattr(supervisor, "STOP_GRACE_SECONDS", 3.0)
    # 端口从本 worker 自己那一段里找:不碰这台机器上真在用的 8189,也不和并行的别的 worker 抢(见那个函数的说明)
    monkeypatch.setattr(records, "FIRST_PORT", first_free_port_of_this_worker())
    shutil.rmtree(pidfiles.pid_dir(), ignore_errors=True)
    yield
    local_services.stop_all()
    supervisor._services.clear()
    supervisor._directories.clear()


@pytest.fixture
def plugged(tmp_path: Path):
    client = fresh_client()
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    (plugin / "main.py").write_text(PLUGIN.replace("__FAKE__", repr(str(FAKE))), encoding="utf-8")
    with SessionLocal() as db:
        db.add(PluginPackage(id=PACKAGE_ID, name="本机服务测试", version="1.0.0", manifest=_manifest(plugin)))
        db.commit()
    return client


def _connection(client, name: str = "") -> str:
    created = client.post(f"/api/plugins/{PACKAGE_ID}/instances", json={"name": name})
    assert created.status_code == 200, created.text
    instance_id = created.json()["id"]
    assert client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True}).status_code == 200
    return instance_id


def _folder(tmp_path: Path, name: str = "comfy", **options: Any) -> str:
    folder = tmp_path / name
    folder.mkdir(exist_ok=True)
    (folder / "fake.json").write_text(json.dumps(options), encoding="utf-8")
    return str(folder)


def _configure(client, instance_id: str, directory: str, **extra: Any):
    return client.put(f"/api/plugins/instances/{instance_id}/local-service",
                      json={"directory": directory, "confirm_run_code": True, **extra})


def _status(client, instance_id: str) -> dict[str, Any]:
    response = client.get(f"/api/plugins/instances/{instance_id}/local-service")
    assert response.status_code == 200, response.text
    return response.json()


def _wait_state(client, instance_id: str, state: str, timeout: float = 20.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        status = _status(client, instance_id)
        if status["state"] == state or time.monotonic() > deadline:
            return status
        time.sleep(0.1)


def _instance(instance_id: str) -> PluginInstance:
    with SessionLocal() as db:
        instance = db.get(PluginInstance, instance_id)
        db.expunge(instance)
        return instance


# ---- 建 ----------------------------------------------------------------------


def test_建要确认_端口往上找第一个空的_写进连接地址(
    plugged, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _connection(plugged, "一号")
    directory = _folder(tmp_path)
    refused = plugged.put(f"/api/plugins/instances/{first}/local-service", json={"directory": directory})
    assert refused.status_code == 422 and "确认" in refused.json()["detail"], "没确认过不运行别人目录里的代码"

    base = records.FIRST_PORT
    # 起点那个端口有人在听:往上找下一个(真的探端口那一半在 test_local_service_supervisor 里)
    monkeypatch.setattr(records, "port_in_use", lambda port: port == base)
    created = _configure(plugged, first, directory)
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["port"] == base + 1 and body["url"] == f"http://127.0.0.1:{base + 1}"
    assert (body["state"], body["title"], body["service"], body["mode"]) == ("stopped", "假服务", "fake", "directory")
    assert body["can_manage"] is True
    with SessionLocal() as db:
        assert db.get(PluginInstance, first).config["server_url"] == f"http://127.0.0.1:{base + 1}", \
            "插件、工作台、模型库读的还是那一个地址"

    second = _connection(plugged, "二号")
    assert _configure(plugged, second, _folder(tmp_path, "other")).json()["port"] == base + 2, "分给别的连接的不再分"

    changed = plugged.put(f"/api/plugins/instances/{first}/local-service",
                          json={"keep_running": True, "extra_args": '--lowvram "--output-directory=D:\\out put"'})
    assert changed.status_code == 200, changed.text
    assert changed.json()["extra_args"] == ["--lowvram", "--output-directory=D:\\out put"], "反斜杠原样、引号括住带空格的"
    assert changed.json()["keep_running"] is True
    unbalanced = plugged.put(f"/api/plugins/instances/{first}/local-service", json={"extra_args": '"--x'})
    assert unbalanced.status_code == 422
    moved = plugged.put(f"/api/plugins/instances/{first}/local-service",
                        json={"directory": _folder(tmp_path, "moved")})
    assert moved.status_code == 422, "换目录就是换一份要运行的代码,要再确认一次"


# ---- 新建连接时就定下在哪跑(插件页「新建连接」弹窗) ------------------------------------------


def _create(client, local_service: dict[str, Any] | None, **body: Any):
    return client.post(f"/api/plugins/{PACKAGE_ID}/instances", json={**body, "local_service": local_service})


def _left_behind() -> tuple[int, int]:
    """库里这个插件的连接、本机服务各有几行。"""
    with SessionLocal() as db:
        instances = db.query(PluginInstance).filter(PluginInstance.package_id == PACKAGE_ID).count()
        return instances, db.query(LocalService).count()


def _declare_permissions(*permissions: str) -> None:
    with SessionLocal() as db:
        package = db.get(PluginPackage, PACKAGE_ID)
        package.manifest = {**package.manifest, "permissions": list(permissions)}
        db.commit()


def test_新建时用我自己装的_一个请求建好_端口和地址宿主给_客户端给的地址不用(
    plugged, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = records.FIRST_PORT
    monkeypatch.setattr(records, "port_in_use", lambda port: port == base)
    directory = _folder(tmp_path)
    created = _create(plugged, {"mode": "directory", "directory": f" {directory} ", "confirm_run_code": True},
                      config={"server_url": "http://192.168.3.99:9999"})
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["config"]["server_url"] == f"http://127.0.0.1:{base + 1}", "地址是宿主选的端口,不是客户端编的那个"
    status = _status(plugged, body["id"])
    assert (status["mode"], status["directory"], status["port"], status["state"]) == ("directory", directory, base + 1, "stopped")
    assert status["url"] == body["config"]["server_url"]
    # 建好马上就能认目录(界面在建好之后接着认一遍、摆在卡片上;确认在弹窗里问过一次)
    found = plugged.post(f"/api/plugins/instances/{body['id']}/local-service/detect",
                         json={"directory": directory, "confirm_run_code": True})
    assert found.status_code == 200 and found.json()["ok"] is True, found.text


def test_新建时让Mosael装_只建那一行不开始装_目录是宿主分的(plugged) -> None:
    created = _create(plugged, {"mode": "managed"})
    assert created.status_code == 200, created.text
    instance_id = created.json()["id"]
    status = _status(plugged, instance_id)
    assert (status["mode"], status["installed"], status["install"]) == ("managed", False, None), "装之前人要先看安装计划"
    assert status["directory"] == str(records.install_root(instance_id))
    assert status["port"] == records.FIRST_PORT
    assert created.json()["config"]["server_url"] == f"http://127.0.0.1:{records.FIRST_PORT}"
    assert status["issue"]["kind"] == "not_installed"


@pytest.mark.parametrize(
    ("local_service", "status", "said"),
    [
        ({"mode": "directory", "directory": "/somewhere"}, 422, "确认"),
        ({"mode": "directory", "directory": "  ", "confirm_run_code": True}, 422, "目录"),
    ],
)
def test_新建时没确认_目录空着_连接也不留下(plugged, local_service: dict, status: int, said: str) -> None:
    response = _create(plugged, local_service)
    assert response.status_code == status and said in response.json()["detail"], response.text
    assert _left_behind() == (0, 0)


def test_新建时找不到空端口_插件没声明服务_连接也不留下(
    plugged, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(records, "PORT_SCAN", 3)
    monkeypatch.setattr(records, "port_in_use", lambda port: True)
    for mode in ("directory", "managed"):
        response = _create(plugged, {"mode": mode, "directory": _folder(tmp_path), "confirm_run_code": True})
        assert response.status_code == 409 and "端口" in response.json()["detail"], response.text
        assert _left_behind() == (0, 0), "连接建了一半(地址还是缺省的那台)不能留下"

    monkeypatch.setattr(records, "port_in_use", lambda port: False)
    with SessionLocal() as db:
        package = db.get(PluginPackage, PACKAGE_ID)
        package.manifest = {**package.manifest, "services": []}
        db.commit()
    response = _create(plugged, {"mode": "managed"})
    assert response.status_code == 422 and "本机服务" in response.json()["detail"]
    assert _left_behind() == (0, 0)


def test_新建时用本机服务要部署管理员_连一台服务器不用(plugged, tmp_path: Path) -> None:
    member = second_client("member")
    refused = _create(member, {"mode": "directory", "directory": _folder(tmp_path), "confirm_run_code": True})
    assert refused.status_code == 403
    assert _create(member, {"mode": "managed"}).status_code == 403
    assert _left_behind() == (0, 0)
    plain = _create(member, None, config={"server_url": "http://127.0.0.1:8188"})
    assert plain.status_code == 200, plain.text
    assert plain.json()["config"]["server_url"] == "http://127.0.0.1:8188"
    assert member.get(f"/api/plugins/instances/{plain.json()['id']}/local-service").json() is None


def test_新建时一起授予看过的权限_没授予的插件不替它认目录(plugged, tmp_path: Path) -> None:
    _declare_permissions("network:fake", "filesystem:write")
    directory = _folder(tmp_path)
    bare = _create(plugged, {"mode": "directory", "directory": directory, "confirm_run_code": True}).json()
    assert bare["pending_permissions"] == ["network:fake", "filesystem:write"]
    refused = plugged.post(f"/api/plugins/instances/{bare['id']}/local-service/detect",
                           json={"directory": directory, "confirm_run_code": True})
    assert refused.status_code == 422, "插件要的权限没授予,它不替这个连接做任何事"

    granted = _create(plugged, {"mode": "directory", "directory": directory, "confirm_run_code": True},
                      grant_permissions=["network:fake", "filesystem:write"])
    assert granted.status_code == 200, granted.text
    assert granted.json()["pending_permissions"] == []
    found = plugged.post(f"/api/plugins/instances/{granted.json()['id']}/local-service/detect",
                         json={"directory": directory, "confirm_run_code": True})
    assert found.status_code == 200 and found.json()["ok"] is True, found.text

    before = _left_behind()
    unknown = _create(plugged, {"mode": "managed"}, grant_permissions=["network:fake", "shell:anything"])
    assert unknown.status_code == 422 and "shell:anything" in unknown.json()["detail"]
    assert _left_behind() == before, "清单没声明的权限授予不了,连接也不留下"


def test_没声明服务的插件建不了(plugged, tmp_path: Path) -> None:
    with SessionLocal() as db:
        package = db.get(PluginPackage, PACKAGE_ID)
        package.manifest = {**package.manifest, "services": []}
        db.commit()
    instance_id = _connection(plugged)
    response = _configure(plugged, instance_id, _folder(tmp_path))
    assert response.status_code == 422 and "本机服务" in response.json()["detail"]


def test_普通成员只能看和用到时起_不能建改起停(plugged, tmp_path: Path) -> None:
    other = second_client("member")
    instance_id = _connection(other)
    assert _configure(other, instance_id, _folder(tmp_path)).status_code == 403
    for action in ("start", "stop", "restart"):
        assert other.post(f"/api/plugins/instances/{instance_id}/local-service/{action}").status_code == 403
    assert other.post(f"/api/plugins/instances/{instance_id}/local-service/detect",
                      json={"directory": "/x", "confirm_run_code": True}).status_code == 403
    assert other.get(f"/api/plugins/instances/{instance_id}/local-service").json() is None
    assert other.post(f"/api/plugins/instances/{instance_id}/local-service/ensure").json() is None, \
        "没用本机服务的连接,ensure 什么都不做"
    admin_sees = plugged.get(f"/api/plugins/instances/{instance_id}/local-service")
    assert admin_sees.status_code == 404, "连接归人:管理员也看不到别人的连接"


# ---- 认目录、补装、本机发现 ----------------------------------------------------------


def test_认目录要确认_事实和问题按读的人的语言(plugged, tmp_path: Path) -> None:
    instance_id = _connection(plugged)
    url = f"/api/plugins/instances/{instance_id}/local-service/detect"
    assert plugged.post(url, json={"directory": _folder(tmp_path)}).status_code == 422
    found = plugged.post(url, json={"directory": _folder(tmp_path), "confirm_run_code": True},
                         headers={"Accept-Language": "en"})
    assert found.status_code == 200, found.text
    body = found.json()
    assert body["ok"] is True
    assert body["facts"] == [{"label": "Version", "value": "0.0.0-fake"}], "没有名字的事实不摆"
    assert body["problems"] == [{"level": "warning", "text": "Something is missing"}]
    assert body["add_nodes"] == {"title": "Add it", "description": "装进 custom_nodes"}
    missing = plugged.post(url, json={"directory": str(tmp_path / "nope"), "confirm_run_code": True}).json()
    assert missing["ok"] is False and missing["problems"][0] == {"level": "error", "text": "没有这个目录"}


def test_补装要确认_装到哪写明(plugged, tmp_path: Path) -> None:
    instance_id = _connection(plugged)
    directory = _folder(tmp_path)
    assert _configure(plugged, instance_id, directory).status_code == 200
    url = f"/api/plugins/instances/{instance_id}/local-service/add-nodes"
    assert plugged.post(url, json={}).status_code == 422
    done = plugged.post(url, json={"confirm": True})
    assert done.status_code == 200, done.text
    assert done.json() == {"installed": ["extra"], "path": str(Path(directory) / "custom_nodes" / "extra"),
                           "message": "装好了"}


def test_本机发现只认本机地址_只给管理员(plugged) -> None:
    found = plugged.get(f"/api/plugins/{PACKAGE_ID}/local-services/discover")
    assert found.status_code == 200, found.text
    assert found.json() == {"servers": [{"url": "http://127.0.0.1:8188", "label": "本机的那台"}]}
    assert second_client("member").get(f"/api/plugins/{PACKAGE_ID}/local-services/discover").status_code == 403


# ---- 起、停、日志 ----------------------------------------------------------------


def test_起停与日志_环境里有宿主给的_没有插件想塞的(plugged, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAEL_SECRET_THING", "不该漏给别人的程序")
    instance_id = _connection(plugged)
    assert _configure(plugged, instance_id, _folder(tmp_path, flags=["--slow", "0.3"])).status_code == 200
    started = plugged.post(f"/api/plugins/instances/{instance_id}/local-service/start")
    assert started.status_code == 200, started.text
    assert started.json()["state"] in ("starting", "running")
    status = _wait_state(plugged, instance_id, "running")
    assert status["state"] == "running", status
    assert status["pid"] and status["started_at"] and status["ready_seconds"] is not None
    logs = plugged.get(f"/api/plugins/instances/{instance_id}/local-service/logs").json()
    assert any("FAKE_ENV=插件给的" in line for line in logs["lines"]), logs
    assert logs["path"].endswith(f"service-{instance_id}.log")

    spec = local_services._launch_spec  # 宿主那一半环境:去掉宿主内部的、插件盖不掉宿主决定的
    with SessionLocal() as db:
        instance = db.get(PluginInstance, instance_id)
        env = spec(db, instance, db.get(LocalService, instance_id)).env
    assert "MOSAEL_SECRET_THING" not in env and "MOSAEL_SNEAKY" not in env
    assert env.get("HTTPS_PROXY") != "http://plugin.invalid", "代理由宿主按这个连接定"
    assert env["HF_ENDPOINT"].startswith("https://") and env["FAKE_ENV"] == "插件给的"

    pid = status["pid"]
    stopped = plugged.post(f"/api/plugins/instances/{instance_id}/local-service/stop")
    assert stopped.json()["state"] == "stopped" and stopped.json()["pid"] is None
    assert not process_alive(pid)


def test_起不来的原因和最后几行日志摆出来(plugged, tmp_path: Path) -> None:
    instance_id = _connection(plugged)
    assert _configure(plugged, instance_id, _folder(tmp_path, flags=["--exit-at-start", "4"])).status_code == 200
    plugged.post(f"/api/plugins/instances/{instance_id}/local-service/start")
    status = _wait_state(plugged, instance_id, "failed")
    assert status["state"] == "failed"
    assert "退出码 4" in status["error"]
    assert any("缺了一个依赖" in line for line in status["failure_lines"])


def test_同一个目录只起一份_端口被占说清楚(plugged, tmp_path: Path) -> None:
    directory = _folder(tmp_path)
    first, second = _connection(plugged, "一号"), _connection(plugged, "二号")
    _configure(plugged, first, directory)
    _configure(plugged, second, directory)
    assert plugged.post(f"/api/plugins/instances/{first}/local-service/start").status_code == 200
    busy = plugged.post(f"/api/plugins/instances/{second}/local-service/start")
    assert busy.status_code == 409 and "一号" in busy.json()["detail"], "第二个直接说这个目录由谁在跑"
    plugged.post(f"/api/plugins/instances/{first}/local-service/stop")

    port = _status(plugged, second)["port"]
    with socket.socket() as holder:
        # 带 SO_REUSEADDR 占:前面几条测试的服务用过这个端口,健康检查留下的 TIME_WAIT 会让不带它的 bind 失败
        if sys.platform != "win32":
            holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        holder.bind(("127.0.0.1", port))
        holder.listen()
        taken = plugged.post(f"/api/plugins/instances/{second}/local-service/start")
    assert taken.status_code == 409 and str(port) in taken.json()["detail"]
    assert _status(plugged, second)["state"] == "stopped"
    assert plugged.post(f"/api/plugins/instances/{second}/local-service/start").status_code == 200, \
        "端口空出来就起得来:上一次没起成的时候目录锁放开了"


def test_改端口要先停_改完地址跟着变_插件把旧地址的数据搬过去(plugged, tmp_path: Path) -> None:
    instance_id = _connection(plugged)
    before = _configure(plugged, instance_id, _folder(tmp_path)).json()["url"]
    plugged.post(f"/api/plugins/instances/{instance_id}/local-service/start")
    _wait_state(plugged, instance_id, "running")
    new_port = _free_port()
    running = plugged.put(f"/api/plugins/instances/{instance_id}/local-service", json={"port": new_port})
    assert running.status_code == 409 and "停" in running.json()["detail"]
    plugged.post(f"/api/plugins/instances/{instance_id}/local-service/stop")
    changed = plugged.put(f"/api/plugins/instances/{instance_id}/local-service", json={"port": new_port})
    assert changed.status_code == 200, changed.text
    after = f"http://127.0.0.1:{new_port}"
    assert changed.json()["url"] == after
    with SessionLocal() as db:
        assert db.get(PluginInstance, instance_id).config["server_url"] == after
    from app.domain.plugins.runtime import data_dir_for

    assert json.loads((data_dir_for(PACKAGE_ID) / "readdress.json").read_text()) == {"from": before, "to": after}
    assert plugged.put(f"/api/plugins/instances/{instance_id}/local-service", json={"port": 80}).status_code == 422


# ---- 用到时起 ------------------------------------------------------------------


def test_用到时起_插件看得到这台归宿主管_任务里报一句进度(plugged, tmp_path: Path) -> None:
    from app.domain.jobs import _progress_listener

    instance_id = _connection(plugged)
    _configure(plugged, instance_id, _folder(tmp_path, flags=["--slow", "0.3"]))
    said: list[str] = []
    token = _progress_listener.set(lambda _fraction, message: said.append(message))
    try:
        with SessionLocal() as db:
            invocation = tools.invoke(db, instance_id, "ping", {})
            output = dict(invocation.output)
    finally:
        _progress_listener.reset(token)
    assert invocation.status == "succeeded", invocation.error
    assert output["service"] == "fake", "插件进程里有 MOSAEL_LOCAL_SERVICE:装完节点要重启时请宿主重启"
    assert output["server"] == _status(plugged, instance_id)["url"]
    assert _status(plugged, instance_id)["state"] == "running", "停着就起,等它就绪再干活"
    assert said and said[0] == "正在启动本机 假服务"

    with SessionLocal() as db:  # 已经在跑:不再报进度,直接干活
        said.clear()
        assert tools.invoke(db, instance_id, "ping", {}).status == "succeeded"
    assert said == []


def test_用到时起_等就绪时不攥连接也不占插件名额(plugged, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """第一次起一台 ComfyUI 可能要一两分钟:等的那一段先交还连接(会话里没有事务),也不占插件名额(别的插件调用不陪它等)。"""
    import threading

    instance_id = _connection(plugged)
    _configure(plugged, instance_id, _folder(tmp_path, flags=["--slow", "0.3"]))
    slots = threading.Semaphore(1)
    monkeypatch.setattr(tools, "PLUGIN_SLOTS", slots)
    wait_ready = local_services._wait_ready
    seen: list[tuple[bool, bool]] = []
    with SessionLocal() as db:

        def watched(process: supervisor.ServiceProcess, title: str) -> None:
            free = slots.acquire(blocking=False)
            if free:
                slots.release()
            seen.append((db.in_transaction(), free))
            wait_ready(process, title)

        monkeypatch.setattr(local_services, "_wait_ready", watched)
        invocation = tools.invoke(db, instance_id, "ping", {})
    assert invocation.status == "succeeded", invocation.error
    assert seen == [(False, True)], "等就绪时会话已经交还了连接、插件名额也还没占"


def test_后台问指纹不替它起_没在跑就说没在跑(plugged, tmp_path: Path) -> None:
    from app.domain.plugins import catalog_watch, service_gate

    instance_id = _connection(plugged)
    _configure(plugged, instance_id, _folder(tmp_path))
    with SessionLocal() as db:
        instance = db.get(PluginInstance, instance_id)
        assert service_gate.idle(db, instance)
        with pytest.raises(PluginDomainError) as caught, service_gate.no_autostart():
            service_gate.prepare(db, instance, progress=lambda *_: None)
    assert caught.value.key == "localServiceIssue_stopped"
    catalog_watch.check_for_changes()
    assert _status(plugged, instance_id)["state"] == "stopped", "为了看一眼目录变没变把它起起来违背「用到时才起」"


def test_对齐目录不是用它_不替它起(plugged, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """后台刷新目录(就绪后那一次、启动时、每分钟问指纹、改配置之后)包在 no_autostart 里:没在跑就直接说没在跑。

    真机上撞到过:一个刚就绪就崩的服务,就绪后那次刷新正好撞上它崩了,于是替它又起了一次 —— 「5 分钟内最多重启 3 次」失效。"""
    from types import SimpleNamespace

    from app.domain.plugins import host_capabilities, instances, service_gate

    instance_id = _connection(plugged)
    _configure(plugged, instance_id, _folder(tmp_path))
    with SessionLocal() as db, service_gate.no_autostart():
        invocation = tools.invoke(db, instance_id, "ping", {})
    assert invocation.status == "failed" and "没在运行" in invocation.error
    assert _status(plugged, instance_id)["state"] == "stopped"

    seen: list[bool] = []
    monkeypatch.setattr(host_capabilities, "_lookup", lambda _capability: (
        lambda _db, _instance, _refresh: seen.append(service_gate._autostart.get()), None, None))
    monkeypatch.setattr(instances, "manifest_for", lambda _db, _instance: SimpleNamespace(provides=["generation"]))
    with SessionLocal() as db:
        host_capabilities.notify(db, db.get(PluginInstance, instance_id), refresh=True)
    assert seen == [False], "宿主侧对齐目录时问插件,不替本机服务起进程"
    assert service_gate._autostart.get() is True, "出了那一段就恢复:用到时照样起"


def test_用到时起_起不来就是那次调用的失败原因(plugged, tmp_path: Path) -> None:
    instance_id = _connection(plugged)
    _configure(plugged, instance_id, _folder(tmp_path, flags=["--hang"], ready=1))
    with SessionLocal() as db:
        invocation = tools.invoke(db, instance_id, "ping", {})
    assert invocation.status == "failed"
    assert "5 秒" in invocation.error and "就绪" in invocation.error, "插件给的就绪上限太短,按下限 5 秒算"


def test_工作台打开前_ensure_等它就绪再回来(plugged, tmp_path: Path) -> None:
    instance_id = _connection(plugged)
    _configure(plugged, instance_id, _folder(tmp_path, flags=["--slow", "0.5"]))
    ready = plugged.post(f"/api/plugins/instances/{instance_id}/local-service/ensure")
    assert ready.status_code == 200, ready.text
    assert ready.json()["state"] == "running"


def test_工作流库的重启_插件说归宿主管就由宿主停了再起(plugged, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.domain import workflow_library

    instance_id = _connection(plugged)
    _configure(plugged, instance_id, _folder(tmp_path))
    restarted: list[str] = []
    monkeypatch.setattr(workflow_library, "_require", lambda _db, _instance: None)
    monkeypatch.setattr(workflow_library.tools, "invoke_host", lambda *_a, **_k: {"host_restart": True})
    monkeypatch.setattr(local_services, "restart", lambda _db, instance, wait=False: restarted.append(instance.id))
    with SessionLocal() as db:
        assert workflow_library.reboot(db, db.get(PluginInstance, instance_id)) == {"back": True}
    assert restarted == [instance_id], "不经 Manager 重启:那会让宿主以为它崩了"

    monkeypatch.setattr(workflow_library.tools, "invoke_host", lambda *_a, **_k: {"back": True})
    restarted.clear()
    with SessionLocal() as db:
        assert workflow_library.reboot(db, db.get(PluginInstance, instance_id)) == {"back": True}
    assert restarted == [], "连一台服务器的照旧由插件经 Manager 重启"


def test_宿主重启_停了再起_等它就绪(plugged, tmp_path: Path) -> None:
    count = tmp_path / "count"
    instance_id = _connection(plugged)
    _configure(plugged, instance_id, _folder(tmp_path, flags=["--count", str(count)]))
    with SessionLocal() as db:
        instance = db.get(PluginInstance, instance_id)
        local_services.ensure_running(db, instance)
        first = local_services.status(db, instance)["pid"]
        local_services.restart(db, instance, wait=True)
        status = local_services.status(db, instance)
    assert status["state"] == "running" and status["pid"] != first
    assert not process_alive(first)
    assert len(count.read_text().splitlines()) == 2


# ---- 后端起来、退出 -----------------------------------------------------------------


def _simulate_backend_crash() -> None:
    """后端被强杀:进程内的看护全没了(不停子进程),子进程自成一组还活着。"""
    for process in supervisor.everyone():
        process._stop.set()
    supervisor._services.clear()
    supervisor._directories.clear()


def test_后端重启_对得上的接回来_对不上的不碰(plugged, tmp_path: Path) -> None:
    kept, stranger = _connection(plugged, "接回来的"), _connection(plugged, "对不上的")
    _configure(plugged, kept, _folder(tmp_path, "a"))
    _configure(plugged, stranger, _folder(tmp_path, "b"))
    for one in (kept, stranger):
        plugged.post(f"/api/plugins/instances/{one}/local-service/start")
        assert _wait_state(plugged, one, "running")["state"] == "running"
    kept_pid, stranger_pid = _status(plugged, kept)["pid"], _status(plugged, stranger)["pid"]
    _simulate_backend_crash()
    record = pidfiles.read_all()
    forged = next(one for one in record if one.instance_id == stranger)
    pidfiles.write(pidfiles.PidRecord(**{**forged.__dict__, "argv": [*forged.argv, "--不是这样起的"]}))

    assert local_services.adopt_orphans() == 1
    status = _status(plugged, kept)
    assert (status["state"], status["pid"], status["adopted"]) == ("running", kept_pid, True)
    assert _status(plugged, stranger)["state"] == "stopped"
    assert process_alive(stranger_pid), "对不上的不杀:不是我们能确定起过的东西"
    assert not pidfiles.path_for(stranger).exists()

    plugged.post(f"/api/plugins/instances/{kept}/local-service/stop")
    assert not process_alive(kept_pid), "接回来的照样停得掉(按 pid 停整组)"
    os.kill(stranger_pid, 9)


def test_后端重启_在_命令行也对_健康检查不过就不接回(plugged, tmp_path: Path) -> None:
    """三样都要对上:进程在、命令行一样,但不响应(这里:记下的端口上没人答)的不算「运行中」,也不碰它。"""
    instance_id = _connection(plugged)
    _configure(plugged, instance_id, _folder(tmp_path))
    plugged.post(f"/api/plugins/instances/{instance_id}/local-service/start")
    pid = _wait_state(plugged, instance_id, "running")["pid"]
    _simulate_backend_crash()
    record = pidfiles.read_all()[0]
    pidfiles.write(pidfiles.PidRecord(**{**record.__dict__, "port": _free_port()}))
    assert pidfiles.same_process(pidfiles.read_all()[0]), "进程在、命令行也对"
    assert local_services.adopt_orphans() == 0
    assert _status(plugged, instance_id)["state"] == "stopped"
    assert process_alive(pid)
    os.kill(pid, 9)


def test_保持运行的跟着起_退出时全部停_连接删了先停(plugged, tmp_path: Path) -> None:
    kept, lazy = _connection(plugged, "保持运行"), _connection(plugged, "用到时起")
    _configure(plugged, kept, _folder(tmp_path, "a"), keep_running=True)
    _configure(plugged, lazy, _folder(tmp_path, "b"))
    local_services.start_kept_running().join(10)
    assert _wait_state(plugged, kept, "running")["state"] == "running"
    assert _status(plugged, lazy)["state"] == "stopped", "没开保持运行的等用到时才起"

    pid = _status(plugged, kept)["pid"]
    local_services.stop_all()
    assert _status(plugged, kept)["state"] == "stopped" and not process_alive(pid)

    plugged.post(f"/api/plugins/instances/{kept}/local-service/start")
    pid = _wait_state(plugged, kept, "running")["pid"]
    assert plugged.delete(f"/api/plugins/instances/{kept}").status_code == 204
    assert not process_alive(pid), "连接删了,它的本机服务先停掉"
    with SessionLocal() as db:
        assert db.get(LocalService, kept) is None


def test_不用本机服务了_停掉并删掉配置(plugged, tmp_path: Path) -> None:
    instance_id = _connection(plugged)
    _configure(plugged, instance_id, _folder(tmp_path))
    plugged.post(f"/api/plugins/instances/{instance_id}/local-service/start")
    pid = _wait_state(plugged, instance_id, "running")["pid"]
    assert plugged.delete(f"/api/plugins/instances/{instance_id}/local-service").status_code == 204
    assert not process_alive(pid)
    assert _status(plugged, instance_id) is None


def test_插件包里声明了服务_插件页知道(plugged) -> None:
    package = next(one for one in plugged.get("/api/plugins").json() if one["id"] == PACKAGE_ID)
    assert package["services"] == [{"key": "fake", "title": "假服务"}]


def test_调用本机服务的操作不走用到时起_没有连接也能问(plugged, tmp_path: Path) -> None:
    """`invoke_service` 是宿主的管理动作:问怎么起的时候它当然还没起,不能先去起它;本机发现时还没有连接。"""
    instance_id = _connection(plugged)
    _configure(plugged, instance_id, _folder(tmp_path))
    with SessionLocal() as db:
        found = tools.invoke_service(db, PACKAGE_ID, "fake", {"op": "service_discover"})
        assert found["servers"][0]["url"] == "http://127.0.0.1:8188"
        with pytest.raises(PluginDomainError) as caught:
            tools.invoke_service(db, PACKAGE_ID, "nope", {"op": "service_discover"})
    assert caught.value.key == "pluginErr_noSuchService"
    assert _status(plugged, instance_id)["state"] == "stopped"
    assert sys.executable  # 插件跑在后端的解释器上(仓库里没有随包解释器时)


# ---- 共用的模型文件夹(拍板 5) ------------------------------------------------------------------


def test_共用的模型文件夹_插件认得出才存_起的时候交给插件_插件调用看得到(plugged, tmp_path: Path) -> None:
    instance_id = _connection(plugged)
    directory = _folder(tmp_path)
    _configure(plugged, instance_id, directory)
    other = tmp_path / "Other" / "models"
    other.mkdir(parents=True)
    url = f"/api/plugins/instances/{instance_id}/local-service"
    refused = plugged.put(url, json={"shared_models": [str(tmp_path)]})
    assert refused.status_code == 422 and f"认不出:{tmp_path}" in refused.json()["detail"], "照插件的原话说是哪一处"
    assert plugged.put(url, json={"shared_models": [str(i) for i in range(21)]}).status_code == 422
    saved = plugged.put(url, json={"shared_models": [f" {other} ", str(other), ""]})
    assert saved.status_code == 200 and saved.json()["shared_models"] == [str(other)], "去空白、去重复"
    # 起的时候交给插件:那几处、宿主给这个连接的那一格(配置写在这里,不写进人家的目录)
    plugged.post(f"{url}/start")
    _wait_state(plugged, instance_id, "running")
    told = json.loads((Path(directory) / "launch.json").read_text(encoding="utf-8"))
    assert told["shared_models"] == [str(other)]
    assert told["config_dir"] == str(records.install_root(instance_id))
    # 插件调用的环境里有它们(下载、写预览图别往里写)
    with SessionLocal() as db:
        invocation = tools.invoke(db, instance_id, "ping", {})
    assert json.loads(invocation.output["shared"]) == [str(other)]
    # 清空
    assert plugged.put(url, json={"shared_models": []}).json()["shared_models"] == []
    member = second_client("member")
    assert member.get(f"/api/plugins/instances/{_connection(member)}/local-service/model-folders").status_code == 403


def test_共用的模型文件夹那一块_每处认成什么_卸载时保留下来的可以加回来(plugged, tmp_path: Path) -> None:
    from app.core.config import settings

    instance_id = _connection(plugged)
    _configure(plugged, instance_id, _folder(tmp_path))
    other = tmp_path / "Other" / "models"
    other.mkdir(parents=True)
    kept = settings.data_dir / "local-services" / "kept-models"
    shutil.rmtree(kept, ignore_errors=True)
    (kept / "ComfyUI · 本机").mkdir(parents=True)
    (kept / ".hidden").mkdir()
    url = f"/api/plugins/instances/{instance_id}/local-service"
    empty = plugged.get(f"{url}/model-folders").json()
    assert empty["folders"] == [] and empty["suggestions"] == [str(kept / "ComfyUI · 本机")]
    assert plugged.put(url, json={"shared_models": [str(other), str(kept / "ComfyUI · 本机")]}).status_code == 200
    body = plugged.get(f"{url}/model-folders").json()
    assert [(one["path"], one["ok"], one["layout"], one["folders"]) for one in body["folders"]] == [
        (str(other), True, "模型文件夹", ["checkpoints"]), (str(kept / "ComfyUI · 本机"), True, "模型文件夹", ["checkpoints"])]
    assert body["running"] is False and body["folders"][0]["loaded"] is None
    assert body["suggestions"] == [], "已经加进来的不再提"
    shutil.rmtree(kept, ignore_errors=True)


# ---- 闲置自动停(释放显存) ----------------------------------------------------------------------


def _busy(**said: Any) -> None:
    """测试插件的 service_busy 照这个答(放在插件的持久目录里)。"""
    from app.domain.plugins.tools import _ensure_data_dir

    (_ensure_data_dir(PACKAGE_ID) / "busy.json").write_text(json.dumps(said), encoding="utf-8")


@pytest.fixture
def minute(monkeypatch: pytest.MonkeyPatch):
    """一分钟按 0.05 秒算:闲置分钟数 1 就是 0.05 秒。"""
    monkeypatch.setattr(local_services, "SECONDS_PER_MINUTE", 0.05)


def _running(client, tmp_path: Path, **extra: Any) -> str:
    instance_id = _connection(client)
    _configure(client, instance_id, _folder(tmp_path), **extra)
    client.post(f"/api/plugins/instances/{instance_id}/local-service/start")
    assert _wait_state(client, instance_id, "running")["state"] == "running"
    return instance_id


def test_闲置够久_问过它没有活_就停_说是闲置停的_用到时再起(plugged, tmp_path: Path, minute) -> None:
    instance_id = _running(plugged, tmp_path)
    url = f"/api/plugins/instances/{instance_id}/local-service"
    assert plugged.put(url, json={"idle_stop_minutes": 1}).json()["idle_stop_minutes"] == 1
    _busy(busy=False)
    time.sleep(0.1)
    assert local_services.check_idle() == [instance_id]
    status = _status(plugged, instance_id)
    assert status["state"] == "stopped" and status["idle_stopped"] is True
    assert "闲置了 1 分钟,自动停了" in status["issue"]["text"]
    with SessionLocal() as db:
        invocation = tools.invoke(db, instance_id, "ping", {})
    assert invocation.status == "succeeded", "用到时照常起"
    status = _status(plugged, instance_id)
    assert status["state"] == "running" and status["idle_stopped"] is False


def test_有活不停_问不到也不停_保持运行和_0_不停(plugged, tmp_path: Path, minute) -> None:
    instance_id = _running(plugged, tmp_path)
    url = f"/api/plugins/instances/{instance_id}/local-service"
    plugged.put(url, json={"idle_stop_minutes": 1})
    _busy(busy=True)
    time.sleep(0.1)
    assert local_services.check_idle() == [], "队列里有在跑、在排的:不停"
    assert supervisor.get(instance_id).idle_seconds() < 0.05, "有活就当它在用:钟重新算"
    _busy(fail=True)
    time.sleep(0.1)
    assert local_services.check_idle() == [], "问不到它有没有活:不停"
    _busy(busy=False)
    plugged.put(url, json={"keep_running": True})
    time.sleep(0.1)
    assert local_services.check_idle() == [], "保持运行的不停"
    plugged.put(url, json={"keep_running": False, "idle_stop_minutes": 0})
    time.sleep(0.1)
    assert local_services.check_idle() == [], "0 = 不自动停"
    assert _status(plugged, instance_id)["state"] == "running"
    assert plugged.put(url, json={"idle_stop_minutes": -1}).status_code == 422
    assert plugged.put(url, json={"idle_stop_minutes": 1441}).status_code == 422


def test_插件调用用完了_工作台开着时告诉一声_闲置的钟都重新算(plugged, tmp_path: Path, minute) -> None:
    instance_id = _running(plugged, tmp_path)
    plugged.put(f"/api/plugins/instances/{instance_id}/local-service", json={"idle_stop_minutes": 1})
    _busy(busy=False)
    process = supervisor.get(instance_id)
    time.sleep(0.1)
    with SessionLocal() as db:
        assert tools.invoke(db, instance_id, "slow", {}).status == "succeeded"
    assert process.idle_seconds() < 0.2, "一次跑了 0.4 秒的调用用完:从它跑完算,不从它开始算"
    time.sleep(0.1)
    assert plugged.post(f"/api/plugins/instances/{instance_id}/local-service/touch").status_code == 204
    assert process.idle_seconds() < 0.05, "工作台开着:告诉一声就重新算"
    assert local_services.check_idle() == []
    other = _connection(plugged)
    assert plugged.post(f"/api/plugins/instances/{other}/local-service/touch").status_code == 204, "没有本机服务:什么都不做"
    assert _status(plugged, other) is None


# ---- 用不了的时候,按本机服务的状态说(不说「检查地址」) ------------------------------------------


def _invoke(instance_id: str, tool: str, *, autostart: bool = True):
    from app.domain.plugins import service_gate

    with SessionLocal() as db:
        if autostart:
            return tools.invoke(db, instance_id, tool, {})
        with service_gate.no_autostart():
            return tools.invoke(db, instance_id, tool, {})


def test_连一台服务器_连不上照插件说的(plugged) -> None:
    """没有本机服务:那句「确认它在运行、地址填对」就是对的,原样留着。"""
    instance_id = _connection(plugged)
    plugged.patch(f"/api/plugins/instances/{instance_id}", json={"config": {"server_url": f"http://127.0.0.1:{_free_port()}"}})
    invocation = _invoke(instance_id, "reach")
    assert invocation.status == "failed" and "地址填对" in invocation.error


def test_停着_后台刷新不替它起_说没在运行_用到时会起(plugged, tmp_path: Path) -> None:
    instance_id = _connection(plugged)
    _configure(plugged, instance_id, _folder(tmp_path))
    invocation = _invoke(instance_id, "reach", autostart=False)
    assert invocation.status == "failed" and "没在运行" in invocation.error and "用到时会自动启动" in invocation.error
    assert "地址" not in invocation.error
    issue = _status(plugged, instance_id)["issue"]
    assert issue["kind"] == "stopped" and "点「启动」" in issue["text"]
    english = plugged.get(f"/api/plugins/instances/{instance_id}/local-service", headers={"Accept-Language": "en"}).json()
    assert english["issue"]["text"].startswith("The local Fake service isn't running")


def test_正在起_不当错误说(plugged, tmp_path: Path) -> None:
    instance_id = _connection(plugged)
    _configure(plugged, instance_id, _folder(tmp_path, flags=["--slow", "3"]))
    plugged.post(f"/api/plugins/instances/{instance_id}/local-service/start")
    status = _wait_state(plugged, instance_id, "starting", timeout=5)
    assert status["issue"]["kind"] == "starting" and "正在启动" in status["issue"]["text"]
    invocation = _invoke(instance_id, "reach", autostart=False)
    assert "正在启动" in invocation.error


def test_起不来_带上原因(plugged, tmp_path: Path) -> None:
    instance_id = _connection(plugged)
    _configure(plugged, instance_id, _folder(tmp_path, flags=["--exit-at-start", "3"]))
    plugged.post(f"/api/plugins/instances/{instance_id}/local-service/start")
    status = _wait_state(plugged, instance_id, "failed")
    assert status["issue"]["kind"] == "failed"
    assert "起不来" in status["issue"]["text"] and "退出码 3" in status["issue"]["text"], "停下时的原因跟着(按读的人的语言)"
    english = plugged.get(f"/api/plugins/instances/{instance_id}/local-service", headers={"Accept-Language": "en"}).json()
    assert "exit code 3" in english["issue"]["text"]


def test_进程在却不应答_说看日志_不说检查地址(plugged, tmp_path: Path) -> None:
    instance_id = _connection(plugged)
    _configure(plugged, instance_id, _folder(tmp_path, flags=["--mute-after", "0.3"]))
    plugged.post(f"/api/plugins/instances/{instance_id}/local-service/start")
    assert _wait_state(plugged, instance_id, "running")["state"] == "running"
    deadline = time.monotonic() + 10
    while (_status(plugged, instance_id)["issue"] or {}).get("kind") != "unresponsive" and time.monotonic() < deadline:
        time.sleep(0.1)
    status = _status(plugged, instance_id)
    assert status["state"] == "running" and status["issue"]["kind"] == "unresponsive"
    invocation = _invoke(instance_id, "reach")
    assert invocation.status == "failed" and "没有应答" in invocation.error and "地址" not in invocation.error


def test_在跑而且应答_插件自己的错照说(plugged, tmp_path: Path) -> None:
    instance_id = _connection(plugged)
    _configure(plugged, instance_id, _folder(tmp_path))
    plugged.post(f"/api/plugins/instances/{instance_id}/local-service/start")
    assert _wait_state(plugged, instance_id, "running")["issue"] is None
    invocation = _invoke(instance_id, "boom")
    assert invocation.status == "failed" and "工作流本身坏了" in invocation.error, "服务好好的:失败原因是插件说的那一句"


@pytest.mark.parametrize(("minor", "kind", "text"), [("", "not_installed", "还没装好"), ("3.12", "rebuild", "运行环境要重建")])
def test_让Mosael装的那一份_还没装好_要重建(plugged, monkeypatch: pytest.MonkeyPatch, minor: str, kind: str, text: str) -> None:
    monkeypatch.setattr(local_services, "base_minor", lambda: "3.13")
    instance_id = _connection(plugged)
    with SessionLocal() as db:
        records.make_managed(db, db.get(PluginInstance, instance_id))
        db.get(LocalService, instance_id).python_minor = minor
        db.commit()
    issue = _status(plugged, instance_id)["issue"]
    assert issue["kind"] == kind and text in issue["text"]
    invocation = _invoke(instance_id, "reach")
    assert invocation.status == "failed" and text in invocation.error
