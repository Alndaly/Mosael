"""让 Mosael 装(ADR 0041 §4)的宿主那一半:一个声明了 `services` 的测试插件,它的 `service_plan` / `service_install` 按控制文件
做几步假的安装(一步一行进度、看取消文件、写安装记录和日志),`service_launch` 让宿主起 tests/fake_local_service.py。走一遍:

- **安装计划**:只给部署管理员;宿主在插件那几步后面加上自己的「试起一次」,写明装在哪(`<数据目录>/local-services/<连接>/`);
- **装**:要确认;连接改成「让 Mosael 装」、端口选好写进地址;插件拿到的是随包的 Python、「管理 → 下载源」里的地址、宿主给的
  日志和 pip 缓存;插件那几步做完宿主试起一次,**健康检查通过才记成装好**(Python 小版本);进度(哪一步、字节、速度)看得到;
- **没装好不让起**(用到时起也一样)、正在装时不能换目录 / 删 / 再装一次;**取消**停在那一步、「接着装」从没做完的开始;
  插件失败原因照说、日志看得到;试起没通过不算装好;
- **运行环境要重建**:Python 小版本对不上就不让起,再装一次就好;
- 后端退出、删连接时正在装的先取消;托管 venv 的对账不碰安装目录;「PyTorch 源」「GitHub 镜像前缀」两项设置;
- **换版本**:更新(要确认;先停下它,插件换完宿主试起一次,**没通过就让插件换回去**,两件都说)、回到上一版、被打断没做完的先「换回」;
  进度、取消和安装是同一套,正在换时用不了的那一句说「正在换版本」。
"""

from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import LocalService, PluginInstance, PluginPackage
from app.domain import local_services
from app.domain.local_services import installer, pidfiles, records, supervisor
from app.domain.plugins.runtime import StreamHooks, _dispatch
from tests.util import first_free_port_of_this_worker, fresh_client, second_client

FAKE = Path(__file__).resolve().parent / "fake_local_service.py"
PACKAGE_ID = "dev.test.managedsvc"

#: 测试插件。控制文件在安装目录的上一层(`local-services/control.json`):每一步多慢、哪一步失败、起的时候带什么参数。
PLUGIN = r'''
import json, os, sys, time
from pathlib import Path

FAKE = __FAKE__
STEPS = ["disk", "fetch", "build"]
TITLES = {"disk": {"zh": "查空间", "en": "Check space"}, "fetch": {"zh": "下载", "en": "Download"},
          "build": {"zh": "装依赖", "en": "Install dependencies"}}

def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()

def cancelled():
    path = os.environ.get("MOSAEL_PLUGIN_CANCEL_FILE", "")
    return bool(path) and os.path.exists(path)

def control(root):
    path = Path(root).parent / "control.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}

def record(root):
    path = Path(root) / "record.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"done": []}

def plan(payload):
    root = payload["directory"]
    done = record(root)["done"]
    return {"ok": True, "platform": {"zh": "测试机", "en": "Test machine"}, "verdict": {"zh": "能装", "en": "Can install"},
            "flavour": "fake", "torch": {"zh": "假 torch", "en": "Fake torch"}, "comfyui": "9.9.9",
            "disk_bytes": 5, "free_bytes": 100,
            "steps": [{"key": key, "title": TITLES[key], "done": key in done} for key in STEPS],
            "downloads": [{"label": "源码", "url": payload["sources"]["github_mirror"] + "https://codeload.github.com/x",
                           "source": "github"},
                          {"label": "依赖", "url": "https://pypi.internal.example/simple", "source": "pip"},
                          {"label": "别的", "url": "https://other.example/x", "source": "ftp"}],
            "problems": control(root).get("problems", [])}

def install(payload):
    root = Path(payload["directory"])
    root.mkdir(parents=True, exist_ok=True)
    (root / "payload.json").write_text(json.dumps(payload), encoding="utf-8")
    options = control(root)
    state = record(root)
    log = open(payload["log"], "a", encoding="utf-8")
    emit({"event": "step", "outline": [{"key": key, "title": TITLES[key], "done": key in state["done"]} for key in STEPS]})
    for key in STEPS:
        if key in state["done"]:
            emit({"event": "step", "key": key, "state": "done"})
            continue
        emit({"event": "step", "key": key, "state": "running"})
        log.write(f"== {key}\n")
        log.flush()
        for done in range(0, 101, 10):
            if cancelled():
                log.write(f"cancelled at {key}\n")
                emit({"ok": False, "error": "cancelled"})
                return None
            emit({"event": "step", "key": key, "state": "running", "done_bytes": done * 1000, "total_bytes": 100000,
                  "item": f"{key}.whl"})
            time.sleep(options.get("slow", {}).get(key, 0))
        if options.get("fail") == key:
            log.write(f"ERROR: {key} broke\n")
            emit({"ok": False, "error": {"zh": f"{key} 这一步坏了", "en": f"step {key} broke"}})
            return None
        state["done"].append(key)
        (root / "record.json").write_text(json.dumps(state), encoding="utf-8")
        emit({"event": "step", "key": key, "state": "done"})
    log.close()
    models = root / "models" / "checkpoints"
    models.mkdir(parents=True, exist_ok=True)
    (models / "mine.safetensors").write_bytes(b"w" * 1000)
    return {"directory": str(root), "python_minor": "3.13"}

def uninstall(payload):
    root = Path(payload["directory"])
    if control(root).get("models_outside"):
        return {"installed": True, "models": str(root.parent), "models_bytes": 1}
    models = root / "models"
    size = sum(one.stat().st_size for one in models.rglob("*") if one.is_file()) if models.is_dir() else 0
    return {"installed": (root / "record.json").is_file(), "models": str(models) if models.is_dir() else "",
            "models_bytes": size}

def versions(payload):
    state = record(payload["directory"])
    options = control(payload["directory"])
    current = state.get("version", "1.0")
    unfinished = options.get("unfinished", "")
    return {"current": current, "latest": "2.0", "update": "" if current == "2.0" or unfinished else "2.0",
            "previous": state.get("previous", "") or options.get("unfinished_back", ""), "unfinished": unfinished}

def change(payload, kind):
    root = Path(payload["directory"])
    (root / f"{kind}-payload.json").write_text(json.dumps(payload), encoding="utf-8")
    options = control(root)
    state = record(root)
    log = open(payload["log"], "a", encoding="utf-8")
    keys = ["fetch", "switch"] if kind == "update" else ["switch"]
    emit({"event": "step", "outline": [{"key": key, "title": TITLES.get(key, {"zh": "换源码", "en": "Switch"}), "done": False}
                                       for key in keys]})
    for key in keys:
        emit({"event": "step", "key": key, "state": "running"})
        log.write(f"== {kind} {key}\n")
        log.flush()
        for done in range(0, 101, 20):
            if cancelled():
                emit({"ok": False, "error": "cancelled"})
                return None
            emit({"event": "step", "key": key, "state": "running", "done_bytes": done, "total_bytes": 100})
            time.sleep(options.get("slow", {}).get(kind, 0))
        emit({"event": "step", "key": key, "state": "done"})
    current = state.get("version", "1.0")
    if options.get("fail") == kind:
        emit({"ok": False, "error": {"zh": f"{kind} 没成,还是 {current}", "en": f"{kind} failed, still {current}"}})
        return None
    if kind == "update":
        state["previous"], state["version"] = current, payload.get("version") or "2.0"
    else:
        state["version"], state["previous"] = state.get("previous") or options.get("unfinished_back") or current, ""
    (root / "record.json").write_text(json.dumps(state), encoding="utf-8")
    log.close()
    return {"directory": str(root), "comfyui": state["version"], "previous": state.get("previous", "")}

def svc(payload):
    op = payload.get("op")
    if op == "service_plan":
        return plan(payload)
    if op == "service_versions":
        return versions(payload)
    if op == "service_uninstall":
        return uninstall(payload)
    if op == "service_launch":
        options = control(payload["directory"])
        version = record(payload["directory"]).get("version", "1.0")
        flags = options.get("launch_flags_by_version", {}).get(version, options.get("launch_flags", []))
        argv = [sys.executable, FAKE, "--port", str(payload["port"]), "--listen", "127.0.0.1", *flags]
        return {"argv": argv, "env": {}, "cwd": payload["directory"], "health_path": "/system_stats", "ready_timeout": 20}
    if op == "service_detect":
        return {"ok": True, "facts": [], "problems": []}
    raise ValueError(op)

request = json.loads(sys.stdin.read())
payload = request.get("input") or {}
try:
    if payload.get("op") in ("service_install", "service_update", "service_rollback"):
        output = install(payload) if payload["op"] == "service_install" else change(payload, payload["op"][len("service_"):])
        if output is not None:
            emit({"ok": True, "output": output})
    else:
        emit({"ok": True, "output": svc(payload)})
except Exception as exc:
    emit({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
'''


def _manifest(path: Path) -> dict[str, Any]:
    return {
        "id": PACKAGE_ID, "name": "让 Mosael 装的测试", "version": "1.0.0", "manifest_version": 8,
        "runtime": {"kind": "process", "entry": "main.py"},
        "instance": {"multiple": True, "config": [{"key": "server_url", "label": "地址", "type": "string", "required": True,
                                                    "default": "http://127.0.0.1:8188"}]},
        "tools": {"expose": "all", "declare": [{"name": "svc", "internal": True, "input_schema": {"type": "object"}}]},
        "services": [{"key": "fake", "title": {"zh": "假服务", "en": "Fake service"}, "tool": "svc"}],
        "_path": str(path),
    }


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(supervisor, "HEALTH_POLL_SECONDS", 0.05)
    monkeypatch.setattr(supervisor, "WATCH_SECONDS", 0.05)
    monkeypatch.setattr(supervisor, "STOP_GRACE_SECONDS", 3.0)
    # 端口从本 worker 自己那一段里找,不和并行的别的 worker 抢(见那个函数的说明)
    monkeypatch.setattr(records, "FIRST_PORT", first_free_port_of_this_worker())
    monkeypatch.setattr(local_services, "base_minor", lambda: "3.13")
    shutil.rmtree(pidfiles.pid_dir(), ignore_errors=True)
    shutil.rmtree(settings.data_dir / records.INSTALLS, ignore_errors=True)
    yield
    installer.cancel_all(wait=10)
    local_services.stop_all()
    installer._runs.clear()
    supervisor._services.clear()
    supervisor._directories.clear()


@pytest.fixture
def plugged(tmp_path: Path):
    client = fresh_client()
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    (plugin / "main.py").write_text(PLUGIN.replace("__FAKE__", repr(str(FAKE))), encoding="utf-8")
    with SessionLocal() as db:
        db.add(PluginPackage(id=PACKAGE_ID, name="让 Mosael 装的测试", version="1.0.0", manifest=_manifest(plugin)))
        db.commit()
    return client


def _connection(client) -> str:
    created = client.post(f"/api/plugins/{PACKAGE_ID}/instances", json={"name": "本机"})
    assert created.status_code == 200, created.text
    instance_id = created.json()["id"]
    assert client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True}).status_code == 200
    return instance_id


def _control(**options: Any) -> None:
    path = settings.data_dir / records.INSTALLS / "control.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(options), encoding="utf-8")


def _url(instance_id: str, tail: str = "") -> str:
    return f"/api/plugins/instances/{instance_id}/local-service{tail}"


def _install(client, instance_id: str, **extra: Any):
    return client.post(_url(instance_id, "/install"), json={"confirm_run_code": True, "flavour": "fake", **extra})


def _status(client, instance_id: str) -> dict[str, Any]:
    response = client.get(_url(instance_id))
    assert response.status_code == 200, response.text
    return response.json()


def _wait(client, instance_id: str, done, timeout: float = 30.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        status = _status(client, instance_id)
        if done(status) or time.monotonic() > deadline:
            return status
        time.sleep(0.05)


def _install_state(state: str):
    return lambda status: (status.get("install") or {}).get("state") == state


# ---- 安装计划 ----------------------------------------------------------------------


def test_安装计划_只给部署管理员_宿主加上试起那一步_写明装在哪(plugged, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ai.runtime import config as runtime_config

    instance_id = _connection(plugged)
    assert plugged.put("/api/settings/install-source", json={"github_mirror": "https://gh.example"}).status_code == 200
    planned = plugged.get(_url(instance_id, "/plan"))
    assert planned.status_code == 200, planned.text
    body = planned.json()
    assert body["ok"] and body["flavour"] == "fake" and body["version"] == "9.9.9" and body["platform"] == "测试机"
    assert [one["key"] for one in body["steps"]] == ["disk", "fetch", "build", "trial"]
    assert body["steps"][-1]["title"] == "试起一次,健康检查通过才算装好"
    assert body["directory"] == str(settings.data_dir / "local-services" / instance_id)
    assert body["downloads"][0]["url"] == "https://gh.example/https://codeload.github.com/x", "插件拿到的是下载源里的地址"
    english = plugged.get(_url(instance_id, "/plan"), headers={"Accept-Language": "en"}).json()
    assert english["platform"] == "Test machine" and english["steps"][-1]["title"].startswith("Start it once")
    member = second_client("member")
    assert member.get(_url(_connection(member), "/plan")).status_code == 403, "那是这台机器上的事:部署管理员"
    runtime_config.refresh()


def test_安装计划写明下载怎么走_跟随全局_自己的代理_直连_绕过列表_每个地址被哪一项下载源改写(plugged) -> None:
    """维护者问「这里的下载是不能走代理的吗」:计划里说清楚插件进程拿到的是哪条路(egress 的同一个决定),密码不摆出来。"""
    from app.ai.runtime import config as runtime_config

    instance_id = _connection(plugged)
    assert plugged.put("/api/settings/install-source", json={"pip_index": "tsinghua"}).status_code == 200
    try:
        # 跟随全局,全局没设代理:Mosael 什么都不给
        body = plugged.get(_url(instance_id, "/plan")).json()
        assert body["route"] == {"kind": "system", "proxy": ""}
        assert all(one["bypass"] is False for one in body["downloads"])
        # 跟随全局,全局设了代理(带账号密码),依赖源的主机在绕过列表里
        assert plugged.put("/api/settings/network", json={"proxy_url": "http://me:secret@127.0.0.1:7897",
                                                          "no_proxy": "pypi.internal.example"}).status_code == 200
        body = plugged.get(_url(instance_id, "/plan")).json()
        assert body["route"] == {"kind": "global", "proxy": "http://***@127.0.0.1:7897"}, "密码不摆出来"
        assert [(one["source"], one["setting"], one["bypass"]) for one in body["downloads"]] == [
            ("github", "", False), ("pip", "清华大学", True), ("", "", False)], "不认的 source 当没有"
        # 这个连接自己的代理:绕过列表只有回环
        plugged.patch(f"/api/plugins/instances/{instance_id}", json={"network": {"mode": "proxy", "proxy_url": "socks5://10.0.0.2:1080"}})
        body = plugged.get(_url(instance_id, "/plan")).json()
        assert body["route"] == {"kind": "own", "proxy": "socks5://10.0.0.2:1080"}
        assert all(one["bypass"] is False for one in body["downloads"])
        # 直连
        plugged.patch(f"/api/plugins/instances/{instance_id}", json={"network": {"mode": "direct"}})
        assert plugged.get(_url(instance_id, "/plan")).json()["route"] == {"kind": "direct", "proxy": ""}
    finally:
        plugged.put("/api/settings/network", json={"proxy_url": "", "no_proxy": ""})
        runtime_config.refresh()


def test_安装计划里插件说的问题_有一条_error_就不能装(plugged) -> None:
    instance_id = _connection(plugged)
    _control(problems=[{"level": "error", "text": {"zh": "空间不够", "en": "No space"}},
                       {"level": "warning", "text": "提醒一下"}])
    body = plugged.get(_url(instance_id, "/plan")).json()
    assert body["ok"] is False and body["supported"] is True, "机器能装,这一次开始不了"
    assert [one["level"] for one in body["problems"]] == ["error", "warning"]


# ---- 装 ----------------------------------------------------------------------------


def test_装要确认_建成让Mosael装_试起通过才记成装好(plugged) -> None:
    instance_id = _connection(plugged)
    refused = plugged.post(_url(instance_id, "/install"), json={"flavour": "fake"})
    assert refused.status_code == 422 and "确认" in refused.json()["detail"]
    started = _install(plugged, instance_id)
    assert started.status_code == 200, started.text
    body = started.json()
    root = settings.data_dir / "local-services" / instance_id
    assert body["mode"] == "managed" and body["directory"] == str(root) and body["installed"] is False
    assert body["install"]["state"] == "installing"
    with SessionLocal() as db:
        assert db.get(PluginInstance, instance_id).config["server_url"] == body["url"], "插件、工作台、模型库读的还是那一个地址"

    status = _wait(plugged, instance_id, _install_state("succeeded"))
    assert status["install"]["state"] == "succeeded", status
    assert status["state"] == "running" and status["installed"] is True and status["python_minor"] == "3.13"
    assert [one["key"] for one in status["install"]["steps"]] == ["disk", "fetch", "build", "trial"]
    assert all(one["done"] for one in status["install"]["steps"])
    payload = json.loads((root / "payload.json").read_text(encoding="utf-8"))
    assert payload["flavour"] == "fake" and payload["python"] and Path(payload["python"]).is_file(), "随包的 Python"
    assert payload["pip_cache"] == str(settings.data_dir / "local-services" / "pip-cache")
    assert set(payload["sources"]) == {"pip_index_url", "pytorch_index_url", "github_mirror"}
    assert payload["sources"]["pytorch_index_url"] == "https://download.pytorch.org/whl", "没配就是官方"
    assert payload["log"].endswith(f"service-install-{instance_id}.log")
    logs = plugged.get(_url(instance_id, "/logs"), params={"source": "install"}).json()
    assert "== fetch" in logs["lines"] and logs["path"] == payload["log"]
    with SessionLocal() as db:
        row = db.get(LocalService, instance_id)
        assert (row.mode, row.python, row.python_minor) == ("managed", "", "3.13")


def test_进度_哪一步_字节_正在下哪个(plugged) -> None:
    instance_id = _connection(plugged)
    _control(slow={"fetch": 0.2})
    _install(plugged, instance_id)
    status = _wait(plugged, instance_id, lambda one: (one.get("install") or {}).get("done_bytes"))
    install = status["install"]
    assert install["step"] == "fetch" and install["item"] == "fetch.whl" and install["total_bytes"] == 100000
    assert [one["done"] for one in install["steps"]] == [True, False, False, False]
    assert install["steps"][1]["title"] == "下载"
    speedy = _wait(plugged, instance_id, lambda one: (one.get("install") or {}).get("speed"))
    assert speedy["install"]["speed"] and speedy["install"]["speed"] > 0, "速度由宿主按字节和时间算"
    plugged.post(_url(instance_id, "/install/cancel"))
    _wait(plugged, instance_id, _install_state("cancelled"))


def test_没装好_不让起_用到时起也说清楚(plugged) -> None:
    instance_id = _connection(plugged)
    _control(fail="build")
    _install(plugged, instance_id)
    failed = _wait(plugged, instance_id, _install_state("failed"))
    assert failed["install"]["error"] == "build 这一步坏了", "插件说的原因原样交回"
    assert failed["install"]["step"] == "build", "停在哪一步"
    english = plugged.get(_url(instance_id), headers={"Accept-Language": "en"}).json()
    assert "step build broke" in english["install"]["error"], "插件按语言分着说的原因,按读的人的语言挑"
    started = plugged.post(_url(instance_id, "/start"))
    assert started.status_code == 409 and "还没装好" in started.json()["detail"]
    ensured = plugged.post(_url(instance_id, "/ensure"))
    assert ensured.status_code == 409 and "接着装" in ensured.json()["detail"]
    logs = plugged.get(_url(instance_id, "/logs"), params={"source": "install"}).json()["lines"]
    assert "ERROR: build broke" in logs


def test_取消_停在那一步_接着装从没做完的开始(plugged) -> None:
    instance_id = _connection(plugged)
    _control(slow={"build": 0.3})
    _install(plugged, instance_id)
    _wait(plugged, instance_id, lambda one: (one.get("install") or {}).get("step") == "build")
    cancelled = plugged.post(_url(instance_id, "/install/cancel"))
    assert cancelled.status_code == 200
    status = _wait(plugged, instance_id, _install_state("cancelled"))
    assert status["install"]["state"] == "cancelled" and status["install"]["step"] == "build"
    plan = plugged.get(_url(instance_id, "/plan")).json()
    assert [one["done"] for one in plan["steps"]] == [True, True, False, False], "插件记下了做完的那几步"
    _control()
    _install(plugged, instance_id)
    done = _wait(plugged, instance_id, _install_state("succeeded"))
    assert done["install"]["state"] == "succeeded" and done["installed"] is True
    log = (settings.data_dir / "logs" / f"service-install-{instance_id}.log").read_text(encoding="utf-8")
    assert "== fetch" not in log and "== build" in log, "接着装:做完的不再做(上一次的日志滚成了 .1)"


def test_装完正好挤在看状态的两下之间_也读不到成了却还没装好(plugged, monkeypatch: pytest.MonkeyPatch) -> None:
    """安装线程先把「装好了」(python_minor)提交进库、再报 succeeded。看状态的要是先读库里那一行、再看这一次安装,装完正好挤在
    两下之间就读到「成了」而 installed 还是 false —— 界面上装好了还摆着安装计划。不赌时机:试起通过后让安装线程停住,看状态的
    一读完那一行就放它走、等它收完尾,再接着往下读。"""
    instance_id = _connection(plugged)
    tried, go_on = threading.Event(), threading.Event()
    real_trial, real_row_of = local_services._trial, records.row_of

    def trial_then_hold(instance_id: str, run: installer.InstallRun) -> None:
        real_trial(instance_id, run)
        tried.set()
        assert go_on.wait(30)

    with SessionLocal() as db:
        def row_then_finish(session, wanted: str):
            row = real_row_of(session, wanted)
            if session is db and not go_on.is_set():
                go_on.set()
                installer.current(wanted).thread.join(30)
            return row

        monkeypatch.setattr(local_services, "_trial", trial_then_hold)
        monkeypatch.setattr(records, "row_of", row_then_finish)
        _install(plugged, instance_id)
        assert tried.wait(30)
        torn = local_services.status(db, db.get(PluginInstance, instance_id))
    assert go_on.is_set() and installer.current(instance_id).state == "succeeded", "装完确实挤在了这一次读的中间"
    install = torn["install"]["state"]
    assert install != "succeeded" or torn["installed"] is True, f"读到成了却还没装好:{torn}"
    assert install != "installing" or torn["issue"]["kind"] == "installing", f"同一次读里两处说的不是一件事:{torn}"
    done = _status(plugged, instance_id)
    assert done["install"]["state"] == "succeeded" and done["installed"] is True


def test_试起没通过_不算装好(plugged) -> None:
    instance_id = _connection(plugged)
    _control(launch_flags=["--exit-at-start", "3"])
    _install(plugged, instance_id)
    status = _wait(plugged, instance_id, _install_state("failed"))
    assert status["install"]["step"] == "trial" and "退出码 3" in status["install"]["error"]
    assert status["installed"] is False and status["python_minor"] == ""
    assert status["state"] == "failed" and status["failure_lines"], "服务自己的日志照样摆出来"


def test_正在装时_不能换目录_不能删_不能再装一次_不能起(plugged, tmp_path: Path) -> None:
    instance_id = _connection(plugged)
    _control(slow={"fetch": 0.3})
    _install(plugged, instance_id)
    for response in (
        plugged.put(_url(instance_id), json={"directory": str(tmp_path), "confirm_run_code": True}),
        plugged.delete(_url(instance_id)),
        _install(plugged, instance_id),
        plugged.post(_url(instance_id, "/start")),
    ):
        assert response.status_code == 409 and "正在装" in response.json()["detail"], response.text
    assert plugged.put(_url(instance_id), json={"keep_running": True}).status_code == 200, "别的设置照样能改"
    plugged.post(_url(instance_id, "/install/cancel"))
    _wait(plugged, instance_id, _install_state("cancelled"))


def test_运行环境要重建_对不上就不让起_再装一次就好(plugged, monkeypatch: pytest.MonkeyPatch) -> None:
    instance_id = _connection(plugged)
    _install(plugged, instance_id)
    _wait(plugged, instance_id, _install_state("succeeded"))
    plugged.post(_url(instance_id, "/stop"))
    monkeypatch.setattr(local_services, "base_minor", lambda: "3.14")
    status = _status(plugged, instance_id)
    assert status["needs_rebuild"] is True and (status["python_minor"], status["base_python_minor"]) == ("3.13", "3.14")
    refused = plugged.post(_url(instance_id, "/start"))
    assert refused.status_code == 409 and "3.13" in refused.json()["detail"] and "重建运行环境" in refused.json()["detail"]
    plan = plugged.get(_url(instance_id, "/plan")).json()
    assert plan["steps"][-1] == {"key": "trial", "title": "试起一次,健康检查通过才算装好", "done": False}
    _install(plugged, instance_id)
    rebuilt = _wait(plugged, instance_id, _install_state("succeeded"))
    assert rebuilt["needs_rebuild"] is False and rebuilt["python_minor"] == "3.14" and rebuilt["state"] == "running"


def test_换回用我自己装的_要给目录要确认_装好的记录清掉(plugged, tmp_path: Path) -> None:
    instance_id = _connection(plugged)
    _install(plugged, instance_id)
    _wait(plugged, instance_id, _install_state("succeeded"))
    assert plugged.put(_url(instance_id), json={"mode": "directory"}).status_code == 422, "换成自己的要给目录"
    assert plugged.put(_url(instance_id), json={"mode": "directory", "directory": str(tmp_path)}).status_code == 422, "要确认"
    switched = plugged.put(_url(instance_id), json={"mode": "directory", "directory": str(tmp_path), "confirm_run_code": True})
    assert switched.status_code == 200, switched.text
    body = switched.json()
    assert (body["mode"], body["directory"], body["python_minor"], body["install"]) == ("directory", str(tmp_path), "", None)
    assert (settings.data_dir / "local-services" / instance_id).is_dir(), "安装目录留着(删它是第三步的卸载)"


def test_后端退出_删连接时_正在装的先取消(plugged) -> None:
    first, second = _connection(plugged), _connection(plugged)
    _control(slow={"fetch": 0.3})
    _install(plugged, first)
    _wait(plugged, first, lambda one: (one.get("install") or {}).get("step") == "fetch")
    local_services.stop_all()
    run = installer.current(first)
    assert run is not None and run.state == installer.CANCELLED and not run.thread.is_alive()
    _install(plugged, second)
    _wait(plugged, second, lambda one: (one.get("install") or {}).get("step") == "fetch")
    thread = installer.current(second).thread
    assert plugged.delete(f"/api/plugins/instances/{second}").status_code == 204
    assert not thread.is_alive() and installer.current(second) is None


# ---- 速度、流式协议 ------------------------------------------------------------------


def test_速度按同一个文件的字节和时间算_换文件重新量(monkeypatch: pytest.MonkeyPatch) -> None:
    """和别的下载同一个算法(core/rate 的滑动平均):第一个点没有速度,之后收敛到真实速率;换了文件重新量。"""
    from app.domain.local_services.logs import ServiceLog

    clock = [100.0]
    #: 只换安装器这个模块读的钟(此前换的是全局的 `time.monotonic`:这条测试跑着时,进程里谁读钟都停在 100 秒)。
    monkeypatch.setattr(installer, "time", SimpleNamespace(monotonic=lambda: clock[0], time=time.time, sleep=time.sleep))
    run = installer.InstallRun("x", ServiceLog(Path("/nonexistent/x.log")), author_locale="zh")
    run.on_step({"event": "step", "outline": [{"key": "fetch", "title": {"zh": "下载", "en": "Download"}}]})
    assert [one.key for one in run.steps] == ["fetch", installer.TRIAL]

    def sample(done: int, item: str = "a.whl") -> float | None:
        run.on_step({"event": "step", "key": "fetch", "state": "running", "done_bytes": done, "total_bytes": 10**9,
                     "item": item})
        return run.speed

    assert sample(0) is None, "只有一个点没有速度"
    for second in range(1, 31):
        clock[0] = 100.0 + second
        speed = sample(second * 4_000_000)
    assert speed is not None and 3_800_000 <= speed <= 4_200_000, speed
    assert sample(10, item="b.whl") is None, "换了文件重新量"
    run.on_step({"event": "step", "key": "fetch", "state": "done"})
    assert run.steps[0].done and run.done_bytes is None and run.speed is None
    run.on_step({"event": "step", "key": "later", "state": "running"})
    assert [one.key for one in run.steps] == ["fetch", "later", installer.TRIAL], "没先说的步骤排在试起之前"


def test_流式协议_step_一行交给_on_step_别的照旧() -> None:
    progress: list[tuple[float, str]] = []
    steps: list[dict[str, Any]] = []
    hooks = StreamHooks(on_progress=lambda f, m: progress.append((f, m)), on_task=lambda _t: None, is_cancelled=lambda: False,
                        on_step=steps.append)
    _dispatch({"event": "step", "key": "fetch", "done_bytes": 1}, hooks)
    _dispatch({"event": "progress", "progress": 0.5, "message": "半"}, hooks)
    _dispatch({"event": "step", "key": "x" * 9000}, hooks)
    assert steps == [{"event": "step", "key": "fetch", "done_bytes": 1}] and progress == [(0.5, "半")], "太大的一行不看"
    quiet = StreamHooks(on_progress=lambda f, m: None, on_task=lambda _t: None, is_cancelled=lambda: False)
    _dispatch({"event": "step", "key": "fetch"}, quiet)  # 没给 on_step:不看,也不出错


# ---- 托管 venv 的对账、下载源设置 ---------------------------------------------------------


def test_托管_venv_的对账不碰本机服务的安装目录(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """随包 Python 换了次版本时,对账删掉 `<托管目录>/venv-*` 里建在旧版本上的;让 Mosael 装的那份 venv 叫 `.venv`、
    住在 `local-services/<连接>/` 下,不归它管 —— 由连接页的「重建运行环境」处理(源码和模型不动)。"""
    from app.ai.runtime import asr_models, config as tts_config, separation_models
    from app.core import interpreter
    from app.db import migrations

    roots = {name: tmp_path / name for name in ("tts", "asr", "sep")}
    monkeypatch.setattr(tts_config, "MANAGED_TTS_ROOT", roots["tts"])
    monkeypatch.setattr(asr_models, "MANAGED_ASR_ROOT", roots["asr"])
    monkeypatch.setattr(separation_models, "MANAGED_SEPARATION_ROOT", roots["sep"])
    monkeypatch.setattr(interpreter, "python_minor", lambda _python: "3.13")
    engine = roots["tts"] / "venv-f5-tts"
    managed = settings.data_dir / records.INSTALLS / "abc" / ".venv"
    for venv in (engine, managed):
        venv.mkdir(parents=True)
        (venv / "pyvenv.cfg").write_text("home = /old\nversion = 3.12.9\n", encoding="utf-8")
    migrations._drop_venvs_built_on_another_python()
    assert not engine.exists(), "对账还在干活(引擎的旧 venv 删了)"
    assert managed.is_dir(), "让 Mosael 装的那份不归它管"
    shutil.rmtree(settings.data_dir / records.INSTALLS, ignore_errors=True)


def test_下载源设置_PyTorch_源和_GitHub_镜像前缀(plugged) -> None:
    from app.ai.runtime import config as runtime_config
    from app.domain.local_services import sources

    url = "/api/settings/install-source"
    initial = plugged.get(url).json()
    assert initial["pytorch_index"] == "" and initial["github_mirror"] == ""
    assert [(one["value"], one["url"]) for one in initial["pytorch_presets"]] == [
        ("pytorch", ""), ("nju", "https://mirror.nju.edu.cn/pytorch/whl")], "官方那一项地址空着(空值 = 官方)"
    assert initial["pytorch_presets"][0]["label"] == "官方(download.pytorch.org)"
    assert plugged.put(url, json={"pytorch_index": "nju"}).json()["pytorch_index"] == "nju"
    assert sources.for_plugin()["pytorch_index_url"] == "https://mirror.nju.edu.cn/pytorch/whl"
    assert plugged.put(url, json={"pytorch_index": "https://torch.example/whl/"}).json()["pytorch_index"] == "https://torch.example/whl"
    assert plugged.put(url, json={"pytorch_index": "pytorch"}).json()["pytorch_index"] == "", "选回官方存空串"
    assert sources.for_plugin()["pytorch_index_url"] == "https://download.pytorch.org/whl"
    assert plugged.put(url, json={"pytorch_index": "mirror.example/whl"}).status_code == 422, "缺 scheme 当场拒"
    saved = plugged.put(url, json={"github_mirror": " https://gh.example "})
    assert saved.json()["github_mirror"] == "https://gh.example/" and sources.for_plugin()["github_mirror"] == "https://gh.example/"
    assert plugged.put(url, json={"github_mirror": "ftp://gh.example"}).status_code == 422
    assert plugged.put(url, json={"github_mirror": ""}).json()["github_mirror"] == ""
    assert plugged.get(url).json()["pip_index"] == initial["pip_index"], "只写给了的那几项"
    assert second_client("member").put(url, json={"github_mirror": "https://x.example"}).status_code == 403
    runtime_config.refresh()


# ---- 换版本(更新、回到上一版)------------------------------------------------------------


def _installed(client) -> str:
    instance_id = _connection(client)
    _install(client, instance_id)
    status = _wait(client, instance_id, _install_state("succeeded"))
    assert status["state"] == "running", status
    return instance_id


def _update(client, instance_id: str, **extra: Any):
    return client.post(_url(instance_id, "/update"), json={"confirm_run_code": True, **extra})


def _versions(client, instance_id: str) -> dict[str, Any]:
    response = client.get(_url(instance_id, "/versions"))
    assert response.status_code == 200, response.text
    return response.json()


def _record(instance_id: str) -> dict[str, Any]:
    return json.loads((settings.data_dir / "local-services" / instance_id / "record.json").read_text(encoding="utf-8"))


def test_更新_要确认_先停下它_插件换完宿主试起一次_成了让它开着(plugged) -> None:
    instance_id = _installed(plugged)
    assert _versions(plugged, instance_id) == {"current": "1.0", "latest": "2.0", "update": "2.0", "previous": "",
                                               "unfinished": ""}
    refused = plugged.post(_url(instance_id, "/update"), json={})
    assert refused.status_code == 422 and "确认" in refused.json()["detail"]
    started = _update(plugged, instance_id)
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["install"]["kind"] == "update" and body["install"]["target"] == "2.0" and body["install"]["state"] == "installing"
    assert body["state"] == "stopped", "源码要换:先停下它"
    assert body["issue"]["kind"] == "updating" and "正在换版本" in body["issue"]["text"]
    status = _wait(plugged, instance_id, _install_state("succeeded"))
    assert status["install"]["state"] == "succeeded", status
    assert status["state"] == "running" and status["installed"] is True
    assert [one["key"] for one in status["install"]["steps"]] == ["fetch", "switch", "trial"]
    assert status["install"]["steps"][-1]["title"] == "试起新版本一次,没通过就换回原来的"
    payload = json.loads((settings.data_dir / "local-services" / instance_id / "update-payload.json").read_text(encoding="utf-8"))
    assert payload["version"] == "2.0" and payload["directory"] == status["directory"]
    assert payload["pip_cache"].endswith("pip-cache") and set(payload["sources"]) == {"pip_index_url", "pytorch_index_url", "github_mirror"}
    assert _versions(plugged, instance_id) == {"current": "2.0", "latest": "2.0", "update": "", "previous": "1.0", "unfinished": ""}
    assert "== update fetch" in plugged.get(_url(instance_id, "/logs"), params={"source": "install"}).json()["lines"], \
        "日志和安装是同一个"
    nothing = _update(plugged, instance_id)
    assert nothing.status_code == 409 and "已经是最新的版本(2.0)" in nothing.json()["detail"]
    member = second_client("member")
    assert member.get(_url(_connection(member), "/versions")).status_code == 403


def test_更新后试起没通过_让插件换回去_说没成_已经换回(plugged) -> None:
    instance_id = _installed(plugged)
    _control(launch_flags_by_version={"2.0": ["--exit-at-start", "3"]})
    assert _update(plugged, instance_id).status_code == 200
    status = _wait(plugged, instance_id, _install_state("failed"))
    error = status["install"]["error"]
    assert "新版本 2.0 试起没通过" in error and "退出码 3" in error and "已经换回 1.0" in error, error
    assert (settings.data_dir / "local-services" / instance_id / "rollback-payload.json").is_file(), "宿主让插件换回去"
    assert _record(instance_id)["version"] == "1.0" and status["state"] != "running"
    english = plugged.get(_url(instance_id), headers={"Accept-Language": "en"}).json()["install"]["error"]
    assert "Went back to 1.0" in english and "exit code 3" in english, "原因按读的人的语言说"
    assert _versions(plugged, instance_id)["update"] == "2.0", "还能再更新"


def test_更新后试起没通过_换回去也没成_两件都说(plugged) -> None:
    instance_id = _installed(plugged)
    _control(launch_flags_by_version={"2.0": ["--exit-at-start", "3"]}, fail="rollback")
    assert _update(plugged, instance_id).status_code == 200
    error = _wait(plugged, instance_id, _install_state("failed"))["install"]["error"]
    assert "试起没通过" in error and "换回 1.0 时也出错了" in error and "rollback 没成" in error and "「换回 1.0」" in error, error


def test_插件那几步没成_原因照说(plugged) -> None:
    instance_id = _installed(plugged)
    _control(fail="update")
    assert _update(plugged, instance_id).status_code == 200
    status = _wait(plugged, instance_id, _install_state("failed"))
    assert status["install"]["error"] == "update 没成,还是 1.0" and status["install"]["step"] == "switch"
    assert not (settings.data_dir / "local-services" / instance_id / "rollback-payload.json").exists(), "插件自己换回去了"


def test_更新_试起时取消_也换回去(plugged) -> None:
    instance_id = _installed(plugged)
    _control(launch_flags_by_version={"2.0": ["--slow", "20"]})
    assert _update(plugged, instance_id).status_code == 200
    _wait(plugged, instance_id, lambda one: (one.get("install") or {}).get("step") == "trial")
    plugged.post(_url(instance_id, "/install/cancel"))
    status = _wait(plugged, instance_id, _install_state("cancelled"))
    assert status["install"]["state"] == "cancelled", status
    assert _record(instance_id)["version"] == "1.0", "试到一半取消:新版本没验过,换回去"
    assert status["state"] == "stopped"


def test_回到上一版_试起一次_再回就没有了(plugged) -> None:
    instance_id = _installed(plugged)
    _update(plugged, instance_id)
    _wait(plugged, instance_id, _install_state("succeeded"))
    started = plugged.post(_url(instance_id, "/rollback"))
    assert started.status_code == 200, started.text
    assert started.json()["install"]["kind"] == "rollback" and started.json()["install"]["target"] == "1.0"
    status = _wait(plugged, instance_id, _install_state("succeeded"))
    assert status["state"] == "running" and [one["key"] for one in status["install"]["steps"]] == ["switch", "trial"]
    assert status["install"]["steps"][-1]["title"] == "试起一次"
    assert _versions(plugged, instance_id) == {"current": "1.0", "latest": "2.0", "update": "2.0", "previous": "", "unfinished": ""}
    again = plugged.post(_url(instance_id, "/rollback"))
    assert again.status_code == 409 and "没有可以回去的上一版" in again.json()["detail"]


def test_换版本之前的拦_没装好_不是让Mosael装_正在装_要重建_没做完的先换回(plugged, monkeypatch: pytest.MonkeyPatch,
                                                                        tmp_path: Path) -> None:
    instance_id = _connection(plugged)
    assert _update(plugged, instance_id).status_code == 404, "没有本机服务"
    _control(fail="build")
    _install(plugged, instance_id)
    _wait(plugged, instance_id, _install_state("failed"))
    refused = _update(plugged, instance_id)
    assert refused.status_code == 409 and "还没装好" in refused.json()["detail"]
    _control(slow={"fetch": 0.3})
    _install(plugged, instance_id)
    busy = _update(plugged, instance_id)
    assert busy.status_code == 409 and "正在装或换版本" in busy.json()["detail"]
    plugged.post(_url(instance_id, "/install/cancel"))
    _wait(plugged, instance_id, _install_state("cancelled"))
    _control()
    _install(plugged, instance_id)
    _wait(plugged, instance_id, _install_state("succeeded"))
    monkeypatch.setattr(local_services, "base_minor", lambda: "3.14")
    rebuild = plugged.post(_url(instance_id, "/rollback"))
    assert rebuild.status_code == 409 and "运行环境要重建" in rebuild.json()["detail"]
    monkeypatch.setattr(local_services, "base_minor", lambda: "3.13")
    _control(unfinished="update", unfinished_back="1.0")
    unfinished = _update(plugged, instance_id)
    assert unfinished.status_code == 409 and "「换回 1.0」" in unfinished.json()["detail"]
    assert plugged.post(_url(instance_id, "/rollback")).status_code == 200, "换回就是收拾它的那一下"
    _wait(plugged, instance_id, _install_state("succeeded"))
    other = _connection(plugged)
    folder = tmp_path / "own"
    folder.mkdir()
    assert plugged.put(_url(other), json={"mode": "directory", "directory": str(folder), "confirm_run_code": True}).status_code == 200
    assert plugged.get(_url(other, "/versions")).status_code == 422, "选目录的那种没有版本可换"


# ---- 卸载(删连接、卸载插件)----------------------------------------------------------------


def _root(instance_id: str) -> Path:
    return settings.data_dir / "local-services" / instance_id


def test_删连接_缺省留着安装目录_问过可以一起删_保留模型挪到_kept_models(plugged) -> None:
    instance_id = _installed(plugged)
    footprint = plugged.get(_url(instance_id, "/footprint"))
    assert footprint.status_code == 200, footprint.text
    body = footprint.json()
    assert body["installed"] is True and body["has_models"] is True and body["models_bytes"] == 1000
    assert body["directory"] == str(_root(instance_id)) and body["bytes"] >= 1000
    assert body["keep_to"] == str(settings.data_dir / "local-services" / "kept-models" / "本机")
    other = _installed(plugged)
    (settings.data_dir / "local-services" / "pip-cache").mkdir(parents=True, exist_ok=True)
    assert plugged.delete(f"/api/plugins/instances/{other}").status_code == 204
    assert _root(other).is_dir(), "缺省留着:删连接不等于删磁盘上的东西"
    assert plugged.delete(f"/api/plugins/instances/{instance_id}", params={"install": "remove", "keep_models": True}).status_code == 204
    assert not _root(instance_id).exists()
    kept = settings.data_dir / "local-services" / "kept-models" / "本机"
    assert (kept / "checkpoints" / "mine.safetensors").read_bytes() == b"w" * 1000, "模型整个挪过去"
    assert not (settings.data_dir / "local-services" / "pip-cache").exists(), "最后一份让 Mosael 装的没了,pip 缓存一起清"
    assert supervisor.get(instance_id) is None or supervisor.get(instance_id).state == "stopped"


def test_删安装目录_不跟着链接出去_同名的保留目录加后缀_还有别的就不清_pip_缓存(plugged, tmp_path: Path) -> None:
    keep_alive = _installed(plugged)
    instance_id = _installed(plugged)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious.txt").write_text("keep", encoding="utf-8")
    (_root(instance_id) / "link-out").symlink_to(outside, target_is_directory=True)
    taken = settings.data_dir / "local-services" / "kept-models" / "本机"
    taken.mkdir(parents=True)
    (settings.data_dir / "local-services" / "pip-cache").mkdir(parents=True, exist_ok=True)
    assert plugged.delete(f"/api/plugins/instances/{instance_id}", params={"install": "remove", "keep_models": True}).status_code == 204
    assert (outside / "precious.txt").read_text(encoding="utf-8") == "keep", "链接只删链接"
    assert (settings.data_dir / "local-services" / "kept-models" / "本机 (2)" / "checkpoints" / "mine.safetensors").is_file()
    assert (settings.data_dir / "local-services" / "pip-cache").is_dir(), "还有一份让 Mosael 装的在用它"
    assert _root(keep_alive).is_dir()


def test_安装目录本身是链接_只删链接(plugged, tmp_path: Path) -> None:
    instance_id = _connection(plugged)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "precious.txt").write_text("keep", encoding="utf-8")
    _root(instance_id).parent.mkdir(parents=True, exist_ok=True)
    _root(instance_id).symlink_to(elsewhere, target_is_directory=True)
    assert plugged.delete(f"/api/plugins/instances/{instance_id}", params={"install": "remove"}).status_code == 204
    assert not _root(instance_id).is_symlink() and (elsewhere / "precious.txt").is_file()


def test_插件说的模型文件夹不在安装目录里_什么都不删(plugged) -> None:
    instance_id = _installed(plugged)
    _control(models_outside=True)
    refused = plugged.delete(f"/api/plugins/instances/{instance_id}", params={"install": "remove", "keep_models": True})
    assert refused.status_code == 409 and "不在安装目录里" in refused.json()["detail"]
    assert _root(instance_id).is_dir() and plugged.get(_url(instance_id)).status_code == 200, "连接和目录都还在"


def test_删安装目录要部署管理员_选目录那一种只删宿主写的配置(plugged, tmp_path: Path) -> None:
    member = second_client("member")
    theirs = _connection(member)
    _root(theirs).mkdir(parents=True)
    (_root(theirs) / "config.yaml").write_text("x", encoding="utf-8")
    assert member.delete(f"/api/plugins/instances/{theirs}", params={"install": "remove"}).status_code == 403
    assert member.get(_url(theirs, "/footprint")).status_code == 403
    assert _root(theirs).is_dir(), "没删"
    instance_id = _connection(plugged)
    folder = tmp_path / "own-comfyui"
    folder.mkdir()
    (folder / "main.py").write_text("x", encoding="utf-8")
    assert plugged.put(_url(instance_id), json={"mode": "directory", "directory": str(folder), "confirm_run_code": True}).status_code == 200
    _root(instance_id).mkdir(parents=True)
    (_root(instance_id) / "config.yaml").write_text("x", encoding="utf-8")
    assert plugged.get(_url(instance_id, "/footprint")).json()["installed"] is False, "只有宿主写的配置"
    assert plugged.delete(f"/api/plugins/instances/{instance_id}", params={"install": "remove"}).status_code == 204
    assert not _root(instance_id).exists() and (folder / "main.py").is_file(), "用户自己的目录从来不碰"


def test_卸载插件_有安装目录先问_留着或者一起删(plugged, tmp_path: Path) -> None:
    first = _installed(plugged)
    assert plugged.get(f"/api/plugins/{PACKAGE_ID}/local-services/installs").json()[0]["instance_id"] == first
    asked = plugged.delete(f"/api/plugins/{PACKAGE_ID}")
    assert asked.status_code == 409 and "先选要不要一起删" in asked.json()["detail"]
    with SessionLocal() as db:
        assert db.get(PluginPackage, PACKAGE_ID) is not None, "没问过不卸"
    assert supervisor.get(first).state == "running", "没问过连服务都不停"
    gone = plugged.delete(f"/api/plugins/{PACKAGE_ID}", params={"local_services": "remove", "keep_models": True})
    assert gone.status_code == 204, gone.text
    assert not _root(first).exists()
    assert (settings.data_dir / "local-services" / "kept-models" / "本机" / "checkpoints" / "mine.safetensors").is_file()
    with SessionLocal() as db:
        assert db.get(PluginPackage, PACKAGE_ID) is None


def test_卸载插件_选留着_安装目录留在磁盘上(plugged) -> None:
    first = _installed(plugged)
    assert plugged.delete(f"/api/plugins/{PACKAGE_ID}", params={"local_services": "keep"}).status_code == 204
    assert (_root(first) / "record.json").is_file()
    assert supervisor.get(first) is None or supervisor.get(first).state == "stopped", "进程照样停掉"
