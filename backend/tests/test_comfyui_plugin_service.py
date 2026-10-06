"""ComfyUI 插件的本机服务操作(ADR 0041 §3):拿夹具目录把「认目录」「怎么起」「补装 pysssss」「本机发现」「改端口搬数据」走一遍。

- **两种便携版选法都认**(外层 `ComfyUI_windows_portable`,或里面那层 `ComfyUI/`),解释器按顺序找:用户指的、便携版
  自带的 `python_embeded`、目录里或上一层的 `venv` / `.venv` —— Windows 的 `Scripts\\python.exe` 和 POSIX 的
  `bin/python` 都用夹具走一遍(这台机器跑不了 Windows,路径逻辑带 `windows` 参数测);
- 试跑 `import torch`:假解释器是一个 shell 脚本,照夹具里写好的那一行回答(MPS / CUDA / 只有 CPU / 导入失败 / 卡住);
  requirements.txt 里必需的包缺哪几个,拿这台的 Python 真跑一次;
- 起:只听本机、装了 Manager 的 pip 包才加 `--enable-manager`、便携版加 `-s`、附加参数里不许写端口和监听地址;
- 补装 pysssss:钉死的 sha256 对不上不装、解包不出 custom_nodes、半截的不留下;
- 主入口:本机服务的操作不需要服务器地址(问怎么起的时候它还没起)。
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui"
TOOLS = PLUGIN / "tools"
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="假解释器是 shell 脚本")
#: 插件 tools/ 下这几个模块按顶层名字导入(插件进程里就是这样):测试之间换掉,免得拿到别的测试改过的那一份。
_PLUGIN_MODULES = ("service", "lines", "pinned", "managed")


@pytest.fixture
def service(monkeypatch):
    saved = {name: sys.modules.pop(name) for name in _PLUGIN_MODULES if name in sys.modules}
    sys.path.insert(0, str(TOOLS))
    try:
        import service as module

        yield module
    finally:
        sys.path.remove(str(TOOLS))
        for name in _PLUGIN_MODULES:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


def _comfy(root: Path, version: str = "0.39.0") -> Path:
    """一份装好的 ComfyUI 的样子:main.py、comfy/、版本文件。"""
    (root / "comfy").mkdir(parents=True)
    (root / "main.py").write_text("print('ComfyUI')\n", encoding="utf-8")
    (root / "comfyui_version.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    (root / "custom_nodes").mkdir()
    return root


def _fake_python(path: Path, trial: dict | None = None, *, manager: bool = False, sleep: float = 0) -> Path:
    """一个假解释器:试跑 `import torch` 那几行时照 `trial` 回答,问 Manager 的 pip 包时照 `manager` 回答。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    answer = json.dumps(trial or {}).replace("'", "'\\''")
    path.write_text(
        "#!/bin/sh\n"
        f"sleep {sleep}\n"
        'case "$2" in\n'
        f"  *torch*) echo 'loading...'; echo 'MOSAEL_TRIAL {answer}' ;;\n"
        f"  *) echo 'MOSAEL_TRIAL {manager}' ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


MPS = {"python": "3.13.15", "manager": True, "torch": "2.14.1", "device": "mps", "gpu": "Apple M3 Max",
       "vram": 36 * 1024 ** 3}


def _facts(found: dict, locale: str = "zh") -> dict[str, str]:
    return {fact["label"][locale]: fact["value"] for fact in found["facts"]}


def _problems(found: dict, locale: str = "zh") -> list[tuple[str, str]]:
    return [(one["level"], one["text"][locale]) for one in found["problems"]]


def test_随包的_ComfyUI_声明了本机服务_归生成那个工具() -> None:
    from app.domain.plugins.manifest import parse

    raw = json.loads((PLUGIN / "mosael.plugin.json").read_text(encoding="utf-8"))
    manifest = parse(raw, str(PLUGIN))
    assert [(one.key, one.title, one.tool) for one in manifest.services] == [("comfyui", "ComfyUI", "comfyui_generation")]


# ---- 认出 ComfyUI、认出解释器 ----------------------------------------------------------


def test_两种便携版选法都认_普通目录也认(service, tmp_path: Path) -> None:
    portable = tmp_path / "ComfyUI_windows_portable"
    inner = _comfy(portable / "ComfyUI")
    (portable / "python_embeded").mkdir()
    for chosen in (portable, inner):
        layout = service.find_layout(chosen)
        assert layout == service.Layout(inner, portable), f"选 {chosen.name} 也认得出"
    plain = _comfy(tmp_path / "plain")
    assert service.find_layout(plain) == service.Layout(plain, None)
    assert service.find_layout(tmp_path / "plain" / "comfy") is None, "选错了一层就是认不出"
    (tmp_path / "empty").mkdir()
    assert service.find_layout(tmp_path / "empty") is None


def test_Windows_便携版用自带的_python_embeded(service, tmp_path: Path) -> None:
    portable = tmp_path / "ComfyUI_windows_portable"
    inner = _comfy(portable / "ComfyUI")
    embedded = portable / "python_embeded" / "python.exe"
    embedded.parent.mkdir()
    embedded.write_bytes(b"")
    layout = service.find_layout(portable)
    assert service.find_python(layout, "", windows=True) == (embedded, "portable")
    assert service.find_layout(inner) == layout


def test_venv_在目录里或上一层_Windows_是_Scripts_python_exe(service, tmp_path: Path) -> None:
    root = _comfy(tmp_path / "ComfyUI")
    layout = service.find_layout(root)
    assert service.find_python(layout, "", windows=True) == (None, "none")

    parent_venv = tmp_path / ".venv" / "Scripts" / "python.exe"
    parent_venv.parent.mkdir(parents=True)
    parent_venv.write_bytes(b"")
    assert service.find_python(layout, "", windows=True) == (parent_venv, "venv"), "上一层的 .venv 也认"
    assert service.find_python(layout, "", windows=False) == (None, "none"), "POSIX 上不认 Scripts\\python.exe"

    own = root / "venv" / "Scripts" / "python.exe"
    own.parent.mkdir(parents=True)
    own.write_bytes(b"")
    assert service.find_python(layout, "", windows=True) == (own, "venv"), "目录里的排在上一层前面"


def test_POSIX_的_venv_是_bin_python_没有就_bin_python3(service, tmp_path: Path) -> None:
    root = _comfy(tmp_path / "ComfyUI")
    layout = service.find_layout(root)
    python3 = root / ".venv" / "bin" / "python3"
    python3.parent.mkdir(parents=True)
    python3.write_bytes(b"")
    assert service.find_python(layout, "", windows=False) == (python3, "venv")
    python = root / ".venv" / "bin" / "python"
    python.write_bytes(b"")
    assert service.find_python(layout, "", windows=False) == (python, "venv")


def test_用户指定的解释器优先_不存在就说不存在(service, tmp_path: Path) -> None:
    root = _comfy(tmp_path / "ComfyUI")
    _fake_python(root / "venv" / "bin" / "python")
    layout = service.find_layout(root)
    conda = tmp_path / "conda" / "bin" / "python"
    conda.parent.mkdir(parents=True)
    conda.write_bytes(b"")
    assert service.find_python(layout, str(conda), windows=False) == (conda, "user"), "他知道 conda 在哪"
    assert service.find_python(layout, str(tmp_path / "nope"), windows=False) == (None, "user")


# ---- 试跑 ----------------------------------------------------------------------


@posix_only
def test_认目录_MPS_的事实_Manager_是_pip_包_没装_pysssss_给补装(service, tmp_path: Path) -> None:
    root = _comfy(tmp_path / "ComfyUI")
    python = _fake_python(root / "venv" / "bin" / "python", MPS)
    found = service.detect({"directory": str(root)}, "zh", windows=False)
    assert found["ok"] is True
    facts = _facts(found)
    assert facts["ComfyUI 版本"] == "0.39.0"
    assert facts["Python"] == f"{python}(3.13.15)"
    assert facts["PyTorch"] == "2.14.1"
    assert facts["显卡"] == "MPS · Apple M3 Max · 统一内存 36 GB"
    assert facts["ComfyUI-Manager"].startswith("pip 包")
    assert facts["ComfyUI-Custom-Scripts(pysssss)"] == "没装"
    assert _problems(found) == [("warning", "没装 ComfyUI-Custom-Scripts(pysssss):模型库的哈希、预览图要靠它")]
    offer = found["add_nodes"]
    assert offer["title"] == {"zh": "补装 pysssss", "en": "Add pysssss"}
    assert str(root / "custom_nodes" / "ComfyUI-Custom-Scripts") in offer["description"]["zh"], "写明装到哪儿"
    english = _facts(service.detect({"directory": str(root)}, "en", windows=False), "en")
    assert english["GPU"] == "MPS · Apple M3 Max · 36 GB unified memory"


@posix_only
def test_认目录_CUDA_老式_Manager_装了_pysssss(service, tmp_path: Path) -> None:
    root = _comfy(tmp_path / "ComfyUI")
    (root / "custom_nodes" / "ComfyUI-Manager").mkdir()
    (root / "custom_nodes" / "comfyui-custom-scripts").mkdir()
    _fake_python(root / ".venv" / "bin" / "python", {
        "python": "3.12.8", "manager": False, "torch": "2.9.0+cu130", "device": "cuda", "gpu": "NVIDIA GeForce RTX 4090",
        "vram": 24 * 1024 ** 3, "cuda": "13.0",
    })
    found = service.detect({"directory": str(root)}, "zh", windows=False)
    assert found["ok"] is True and found["add_nodes"] is None
    facts = _facts(found)
    assert facts["显卡"] == "CUDA 13.0 · NVIDIA GeForce RTX 4090 · 显存 24 GB"
    assert facts["ComfyUI-Manager"].startswith("老式节点"), "Manager 的老装法(custom_nodes 里,不分大小写)"
    assert facts["ComfyUI-Custom-Scripts(pysssss)"] == "已装"
    assert found["problems"] == []


@posix_only
def test_认目录_torch_导入不了就不让起_只有_CPU_提醒会很慢(service, tmp_path: Path) -> None:
    root = _comfy(tmp_path / "ComfyUI")
    python = root / "venv" / "bin" / "python"
    _fake_python(python, {"python": "3.13.15", "manager": False, "torch_error": "ModuleNotFoundError: No module named 'torch'"})
    broken = service.detect({"directory": str(root)}, "zh", windows=False)
    assert broken["ok"] is False
    assert any(level == "error" and "导入不了 torch" in text and "No module named" in text
               for level, text in _problems(broken)), "说清楚是哪一步不行"
    assert any("没装 ComfyUI-Manager" in text for _level, text in _problems(broken))

    _fake_python(python, {"python": "3.13.15", "torch": "2.14.1", "device": "cpu"})
    cpu = service.detect({"directory": str(root)}, "zh", windows=False)
    assert cpu["ok"] is True and _facts(cpu)["显卡"] == "只有 CPU"
    assert any(level == "warning" and "只能用 CPU" in text for level, text in _problems(cpu))


@posix_only
def test_认目录_试跑卡住有上限(service, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "TRIAL_TIMEOUT_SECONDS", 0.5)
    root = _comfy(tmp_path / "ComfyUI")
    _fake_python(root / "venv" / "bin" / "python", MPS, sleep=5)
    found = service.detect({"directory": str(root)}, "zh", windows=False)
    assert found["ok"] is False
    assert any(level == "error" and "import torch" in text for level, text in _problems(found))


@posix_only
def test_认目录_torch_能导入但缺_ComfyUI_要的包_也不让起(service, tmp_path: Path) -> None:
    """真机上撞到过:conda base 里有 torch 2.8、MPS 也能用,起 ComfyUI 0.38 却因为缺 alembic、comfy-aimdo 直接退出。"""
    root = _comfy(tmp_path / "ComfyUI")
    (root / "custom_nodes" / "comfyui-manager").mkdir()
    (root / "custom_nodes" / "ComfyUI-Custom-Scripts").mkdir()
    python = _fake_python(tmp_path / "conda" / "bin" / "python", {**MPS, "manager": False, "missing": ["alembic", "comfy-aimdo"]})
    found = service.detect({"directory": str(root), "python": str(python)}, "zh", windows=False)
    assert found["ok"] is False, "起不来的不让存"
    assert _facts(found)["PyTorch"] == "2.14.1", "torch 那一半照样摆出来"
    [(level, text)] = _problems(found)
    assert level == "error" and "alembic、comfy-aimdo" in text
    assert f"{python} -m pip install -r {root / 'requirements.txt'}" in text, "说清楚在哪个环境里装什么"

    many = [f"pkg{index}" for index in range(11)]
    _fake_python(python, {**MPS, "missing": ["torch", *many]})
    [(_level, text)] = _problems(service.detect({"directory": str(root), "python": str(python)}, "en", windows=False), "en")
    assert "pkg7 and 3 more" in text and "torch," not in text, "列前 8 个;torch 缺不缺上面另说"


def test_必需的包照_requirements_txt_非必需那句注释以下的不算(service, tmp_path: Path) -> None:
    root = _comfy(tmp_path / "ComfyUI")
    assert service.required_packages(root) == [], "没有 requirements.txt 就不查"
    (root / "requirements.txt").write_text(
        "comfyui-frontend-package==1.53.10\n# 注释\ntorch\nnumpy>=1.25.0  # 行尾注释\ntransformers[torch]>=4.50.3\n"
        "av>=17.0.0; sys_platform != 'emscripten'\n-r more.txt\ngit+https://example.invalid/x.git\n\n"
        "#non essential dependencies:\nkornia>=0.7.1\nspandrel\n",
        encoding="utf-8",
    )
    assert service.required_packages(root) == ["comfyui-frontend-package", "torch", "numpy", "transformers", "av"]


def test_试跑在那个_Python_里按包名查_装了的不报_没装的报(service, tmp_path: Path) -> None:
    """不用假解释器:拿跑测试的这个 Python 真跑一次试跑的那几行(这里没有 torch,只看缺包那一半)。"""
    root = _comfy(tmp_path / "ComfyUI")
    (root / "requirements.txt").write_text("pytest\nPYTEST\nTyping-Extensions\nsurely-not-installed-mosael-xyz==1.0\n", encoding="utf-8")
    said = service._run_python(Path(sys.executable), service._trial_code(service.required_packages(root)), root, 120)
    assert json.loads(said)["missing"] == ["surely-not-installed-mosael-xyz"], "包名大小写、- 和 _ 不一样也认得出"


def test_认目录_认不出_找不到解释器_都说清楚下一步(service, tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    missing = service.detect({"directory": str(tmp_path / "empty")}, "zh", windows=False)
    assert missing["ok"] is False and "main.py" in _problems(missing)[0][1]
    root = _comfy(tmp_path / "ComfyUI")
    no_python = service.detect({"directory": str(root)}, "zh", windows=False)
    assert no_python["ok"] is False
    assert any(level == "error" and "venv" in text and "指一个" in text for level, text in _problems(no_python))
    wrong = service.detect({"directory": str(root), "python": str(tmp_path / "nope")}, "zh", windows=False)
    assert any("指定的 Python 不存在" in text for _level, text in _problems(wrong))


# ---- 怎么起 --------------------------------------------------------------------


def test_起_只听本机_装了_Manager_的_pip_包才加_enable_manager(service, tmp_path: Path) -> None:
    root = _comfy(tmp_path / "ComfyUI")
    python = root / "venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"")
    told = service.launch({"directory": str(root), "port": 8189, "listen_lan": False, "extra_args": ["--lowvram"]}, "zh",
                          windows=False, has_manager=lambda *_: True)
    assert told["argv"] == [str(python), str(root / "main.py"), "--listen", "127.0.0.1", "--port", "8189",
                            "--enable-manager", "--lowvram"]
    assert (told["cwd"], told["health_path"], told["ready_timeout"]) == (str(root), "/system_stats", 180)
    assert told["env"]["PYTHONUNBUFFERED"] == "1", "日志写的是文件:不带缓冲,宿主那边才跟得上"
    lan = service.launch({"directory": str(root), "port": 8190, "listen_lan": True}, "zh", windows=False,
                         has_manager=lambda *_: False)
    assert lan["argv"][2:6] == ["--listen", "0.0.0.0", "--port", "8190"] and "--enable-manager" not in lan["argv"], \
        "老式节点或没装 Manager 不加 --enable-manager"


def test_起_便携版用自带的解释器加_s(service, tmp_path: Path) -> None:
    portable = tmp_path / "ComfyUI_windows_portable"
    inner = _comfy(portable / "ComfyUI")
    embedded = portable / "python_embeded" / "python.exe"
    embedded.parent.mkdir()
    embedded.write_bytes(b"")
    told = service.launch({"directory": str(portable), "port": 8189}, "zh", windows=True, has_manager=lambda *_: False)
    assert told["argv"][:3] == [str(embedded), "-s", str(inner / "main.py")], "和便携版自己的启动脚本一样不读用户目录的 site-packages"
    assert told["cwd"] == str(inner)


@pytest.mark.parametrize("flag", ["--port", "--port=9000", "--listen", "--listen=0.0.0.0"])
def test_起_附加参数里不许写端口和监听地址(service, tmp_path: Path, flag: str) -> None:
    root = _comfy(tmp_path / "ComfyUI")
    (root / "venv" / "bin").mkdir(parents=True)
    (root / "venv" / "bin" / "python").write_bytes(b"")
    from lines import ComfyError

    with pytest.raises(ComfyError, match="附加参数"):
        service.launch({"directory": str(root), "port": 8189, "extra_args": [flag]}, "zh", windows=False,
                       has_manager=lambda *_: False)


def test_起_认不出目录_找不到解释器_端口不对都不起(service, tmp_path: Path) -> None:
    from lines import ComfyError

    with pytest.raises(ComfyError, match="认不出"):
        service.launch({"directory": str(tmp_path), "port": 8189}, "zh", windows=False)
    root = _comfy(tmp_path / "ComfyUI")
    with pytest.raises(ComfyError, match="Python"):
        service.launch({"directory": str(root), "port": 8189}, "zh", windows=False)
    (root / "venv" / "bin").mkdir(parents=True)
    (root / "venv" / "bin" / "python").write_bytes(b"")
    with pytest.raises(ComfyError, match="端口"):
        service.launch({"directory": str(root), "port": 80}, "zh", windows=False, has_manager=lambda *_: False)


@posix_only
def test_起_问_Manager_的_pip_包用的是那个解释器(service, tmp_path: Path) -> None:
    root = _comfy(tmp_path / "ComfyUI")
    python = _fake_python(root / "venv" / "bin" / "python", manager=True)
    assert service.manager_pip(python, root) is True
    _fake_python(python, manager=False)
    assert service.manager_pip(python, root) is False


# ---- 补装 pysssss ----------------------------------------------------------------


def _archive(members: dict[str, bytes], top: str = "ComfyUI-Custom-Scripts-abc") -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(f"{top}/{name}" if not name.startswith(("/", "..")) else name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _serve_archive(service, monkeypatch, tmp_path: Path, data: bytes, *, sha: str | None = None) -> None:
    source = tmp_path / "pysssss.tar.gz"
    source.write_bytes(data)
    monkeypatch.setattr(service, "PYSSSSS", dataclasses.replace(
        service.PYSSSSS, url=source.as_uri(), sha256=sha or hashlib.sha256(data).hexdigest(), size=len(data)))


def test_补装_按钉死的_sha256_校验_解进_custom_nodes(service, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _comfy(tmp_path / "ComfyUI")
    _serve_archive(service, monkeypatch, tmp_path, _archive({"__init__.py": b"# pysssss\n", "web/js/a.js": b"x"}))
    done = service.add_nodes({"directory": str(root)}, "zh")
    target = root / "custom_nodes" / "ComfyUI-Custom-Scripts"
    assert done["installed"] == ["ComfyUI-Custom-Scripts"] and done["path"] == str(target)
    assert (target / "__init__.py").read_bytes() == b"# pysssss\n" and (target / "web" / "js" / "a.js").exists(), \
        "压缩包里那一层顶目录去掉"
    assert [one.name for one in (root / "custom_nodes").iterdir()] == ["ComfyUI-Custom-Scripts"], "不留临时目录"
    again = service.add_nodes({"directory": str(root)}, "zh")
    assert again["installed"] == [] and "已经装着了" in again["message"]["zh"]


def test_补装_sha256_对不上不装(service, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _comfy(tmp_path / "ComfyUI")
    _serve_archive(service, monkeypatch, tmp_path, _archive({"__init__.py": b"x"}), sha="0" * 64)
    from lines import ComfyError

    with pytest.raises(ComfyError, match="sha256"):
        service.add_nodes({"directory": str(root)}, "zh")
    assert list((root / "custom_nodes").iterdir()) == []


def test_补装_压缩包里有越界路径就不装_半截的不留下(service, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _comfy(tmp_path / "ComfyUI")
    _serve_archive(service, monkeypatch, tmp_path, _archive({"ok.py": b"x", "../../evil.py": b"x"}))
    from lines import ComfyError

    with pytest.raises(ComfyError, match="解不开"):
        service.add_nodes({"directory": str(root)}, "zh")
    assert list((root / "custom_nodes").iterdir()) == []
    assert not (tmp_path / "evil.py").exists()


class _Mirror(BaseHTTPRequestHandler):
    """假的 GitHub 镜像:记下被要的路径(前缀后面接的是原地址),回同一个压缩包。"""

    body = b""
    asked: list[str] = []

    def do_GET(self) -> None:  # noqa: N802
        type(self).asked.append(self.path)
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *_args: object) -> None:
        return


def test_补装_走_GitHub_镜像前缀_内容照样按_sha256_校验(service, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = _archive({"__init__.py": b"# pysssss\n"})
    handler = type("Mirror", (_Mirror,), {"body": data, "asked": []})
    mirror = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=mirror.serve_forever, daemon=True).start()
    prefix = f"http://127.0.0.1:{mirror.server_address[1]}"
    try:
        root = _comfy(tmp_path / "ComfyUI")
        monkeypatch.setattr(service, "PYSSSSS", dataclasses.replace(service.PYSSSSS, sha256=hashlib.sha256(data).hexdigest()))
        done = service.add_nodes({"directory": str(root), "sources": {"github_mirror": prefix}}, "zh")
        assert done["installed"] == ["ComfyUI-Custom-Scripts"]
        assert handler.asked == [f"/{service.PYSSSSS.url}"], "前缀后面接原地址(常见的 GitHub 加速都这么用)"
        # 镜像给了别的内容:sha256 对不上,不装
        other = _comfy(tmp_path / "other" / "ComfyUI")
        monkeypatch.setattr(service, "PYSSSSS", dataclasses.replace(service.PYSSSSS, sha256="0" * 64))
        from lines import ComfyError

        with pytest.raises(ComfyError, match="sha256") as caught:
            service.add_nodes({"directory": str(other), "sources": {"github_mirror": prefix + "/"}}, "zh")
        assert prefix in str(caught.value), "说清楚是从哪个地址下的"
        assert list((other / "custom_nodes").iterdir()) == []
    finally:
        mirror.shutdown()


def test_钉死的_pysssss_地址就是那个提交(service) -> None:
    assert service.PYSSSSS_COMMIT in service.PYSSSSS.url and len(service.PYSSSSS.sha256) == 64
    assert service.PYSSSSS.url.startswith("https://codeload.github.com/"), "GitHub 上的:能接 GitHub 镜像前缀"


# ---- 本机发现、搬数据 --------------------------------------------------------------


class _Stats(BaseHTTPRequestHandler):
    body = b""

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *_args: object) -> None:
        return


def _serve(body: dict) -> ThreadingHTTPServer:
    handler = type("Handler", (_Stats,), {"body": json.dumps(body).encode()})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_本机发现_只认回了_ComfyUI_那份系统信息的(service) -> None:
    comfy = _serve({"system": {"comfyui_version": "0.39.0"}, "devices": []})
    other = _serve({"status": "ok"})
    try:
        ports = (comfy.server_address[1], other.server_address[1], 9)
        found = service.discover({}, "zh", ports=ports)["servers"]
    finally:
        comfy.shutdown()
        other.shutdown()
    assert found == [{"url": f"http://127.0.0.1:{ports[0]}", "label": {
        "zh": f"本机的 ComfyUI 0.39.0(端口 {ports[0]})", "en": f"ComfyUI 0.39.0 on this computer (port {ports[0]})"}}]
    assert service.DISCOVER_PORTS == (8188, 8000), "ComfyUI 自己的缺省端口和官方 Desktop 的"


def test_改端口_按旧地址存的数据搬到新地址名下(service, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAEL_PLUGIN_DATA_DIR", str(tmp_path))

    def key(url: str) -> str:
        return hashlib.sha1(url.encode()).hexdigest()[:12]

    old, new = key("http://127.0.0.1:8189"), key("http://127.0.0.1:8200")
    (tmp_path / f"library-{old}.json").write_text("{}", encoding="utf-8")
    (tmp_path / f"tools-{old}.json").write_text("{}", encoding="utf-8")
    (tmp_path / f"library-{key('http://192.168.1.2:8188')}.json").write_text("{}", encoding="utf-8")
    moved = service.readdress({"from": "http://127.0.0.1:8189/", "to": "http://127.0.0.1:8200"}, "zh")
    assert moved == {"moved": 2}
    assert sorted(one.name for one in tmp_path.iterdir()) == sorted(
        [f"library-{new}.json", f"tools-{new}.json", f"library-{key('http://192.168.1.2:8188')}.json"]), \
        "和 model_files.data_file、tooling 的缓存同一个算法(地址规整成 Comfy.base 再取 sha1);别的服务器的不动"


# ---- 主入口 --------------------------------------------------------------------


def test_主入口_本机服务的操作不需要服务器地址(tmp_path: Path) -> None:
    request = {"tool": "comfyui_generation", "input": {"op": "service_detect", "directory": str(tmp_path)}, "locale": "zh"}
    env = {key: value for key, value in os.environ.items() if key not in ("SERVER_URL",)}
    result = subprocess.run([sys.executable, str(TOOLS / "main.py")], input=json.dumps(request), capture_output=True,
                            text=True, env=env, timeout=60)
    response = json.loads(result.stdout.strip().splitlines()[-1])
    assert response["ok"] is True, response
    assert response["output"]["ok"] is False and "main.py" in response["output"]["problems"][0]["text"]["zh"]
