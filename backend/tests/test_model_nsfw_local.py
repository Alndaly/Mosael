"""本机识别 NSFW 预览图(ADR 0038 §9「本地识别怎么带」):权重怎么下、识别怎么排队、结果怎么记。

和模型库连起来的那一段(列的时候带上、看显示着的那张)在 test_plugin_model_library 里。
"""

from __future__ import annotations

import hashlib
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from PIL import Image

from app.ai.runtime import nsfw_models
from app.domain import model_nsfw_local
from tests.util import fresh_client, second_client


@pytest.fixture(autouse=True)
def _desktop(monkeypatch):
    """这里的服务起在本机回环上,是桌面版的情形:连接里填的(部署配的)地址照连(core/outbound_guard)。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "local_desktop", True)


@pytest.fixture(autouse=True)
def _clean():
    """每条从头来:没下权重、没有记着的结果(测试的数据目录是整轮共用的一个临时目录)。"""

    def reset() -> None:
        model_nsfw_local.forget()
        nsfw_models._store.clear(nsfw_models.NSFW_CLASSIFIER)
        shutil.rmtree(nsfw_models.root(), ignore_errors=True)

    reset()
    yield
    reset()


class _Weights:
    """本机一个 HTTP 服务,替 HuggingFace 交那个权重文件。"""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.paths: list[str] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 — http.server 的约定
                outer.paths.append(self.path)
                self.send_response(200)
                self.send_header("Content-Length", str(len(outer.body)))
                self.end_headers()
                self.wfile.write(outer.body)

            def log_message(self, *_args) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        # shutdown() 停掉 serve_forever 的循环;server_close() 关掉监听的套接字(不关的话 fd 留到进程退出);再等服务线程走完。
        self.server.shutdown()
        self.server.server_close()
        self._thread.join(timeout=30)


def _wait_install() -> dict:
    import time

    for _ in range(200):
        status = nsfw_models.status()
        if status["status"] != "installing":
            return status
        time.sleep(0.05)
    raise AssertionError("还在下")


def test_权重第一次用时下_钉死版本_校验SHA256_对不上拒装(monkeypatch) -> None:
    web = _Weights(b"not the weights")
    try:
        monkeypatch.setattr(nsfw_models, "download_url", lambda: f"{web.url}/{nsfw_models.REPO}/resolve/{nsfw_models.REVISION}/model.safetensors")
        assert nsfw_models.status() == {"status": "missing", "message": "", "message_params": {}, "size_bytes": 22_404_720}
        nsfw_models.start_install()
        failed = _wait_install()
        assert failed["status"] == "failed" and failed["message"] == "runtimeErr_checksumMismatch", "下来的不是核对过的那一个:不装"
        assert not nsfw_models.ready() and not list(nsfw_models.root().glob("*.download")), "半截、不对的文件到不了正式位置"

        monkeypatch.setattr(nsfw_models, "SHA256", hashlib.sha256(web.body).hexdigest())
        nsfw_models.start_install()
        assert _wait_install()["status"] == "installed"
        assert nsfw_models.ready() and nsfw_models.weights_path().read_bytes() == web.body
        assert web.paths[-1] == f"/{nsfw_models.REPO}/resolve/{nsfw_models.REVISION}/model.safetensors", "地址钉在那个版本上"
    finally:
        web.close()


def test_下载走设置里选的HuggingFace源(monkeypatch) -> None:
    monkeypatch.setattr("app.ai.runtime.config.get", lambda: type("C", (), {"hf_endpoint": "https://hf-mirror.com"})())
    assert nsfw_models.download_url() == (
        "https://hf-mirror.com/Marqo/nsfw-image-detection-384/resolve/0c26ec22111b83f106d72a55f611ec35962bcb65/model.safetensors")


def test_下载只给部署管理员_状态谁都能看(monkeypatch) -> None:
    admin = fresh_client()
    started: list[bool] = []
    monkeypatch.setattr(nsfw_models, "start_install", lambda: started.append(True) or nsfw_models.status())
    mate = second_client("mate")
    assert mate.get("/api/model-library/local-nsfw").json()["status"] == "missing"
    assert mate.post("/api/model-library/local-nsfw/install").status_code == 403
    assert not started
    answer = admin.post("/api/model-library/local-nsfw/install")
    assert answer.status_code == 200 and started == [True]
    assert answer.json()["size_bytes"] == 22_404_720 and answer.json()["pending"] == 0


def _original(path: Path, color: tuple[int, int, int], kind: str = "image/webp") -> model_nsfw_local.Source:
    """宿主缓存里取回来的一份原样(和它的类型)。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 96), color).save(path, "WEBP")
    return model_nsfw_local.Source(path, kind)


@pytest.fixture
def classifier(monkeypatch):
    """权重「下好了」(正式位置上有个文件),识别换成看颜色:偏红的算 NSFW。记下每次看的是什么颜色。"""
    path = nsfw_models.weights_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"weights")
    seen: list[tuple[int, int, int]] = []

    def probability(image: Image.Image) -> float:
        red, green, blue = image.convert("RGB").getpixel((8, 8))
        seen.append((red, green, blue))
        return 0.93 if red > 150 and green < 100 else 0.04

    monkeypatch.setattr(model_nsfw_local, "_probability", probability)
    return seen


def test_没算过的排进队_下次就有_按图的内容记_重启之后从盘上读(classifier, tmp_path) -> None:
    red = _original(tmp_path / "a", (210, 30, 40))
    same = model_nsfw_local.Source(tmp_path / "b", "image/webp")
    same.original.write_bytes(red.original.read_bytes())
    green = _original(tmp_path / "c", (30, 170, 60))

    assert model_nsfw_local.signal(red) is None, "列的时候不等它"
    model_nsfw_local.signal(same)
    model_nsfw_local.signal(green)
    assert model_nsfw_local.wait_idle()
    assert model_nsfw_local.signal(red) == {"source": "local", "nsfw": True, "score": 0.93}
    assert model_nsfw_local.signal(same) == {"source": "local", "nsfw": True, "score": 0.93}, "同一张图换了名字不再算"
    assert model_nsfw_local.signal(green) == {"source": "local", "nsfw": False, "score": 0.04}
    assert len(classifier) == 2, "两张不同的图各算一次"
    assert model_nsfw_local.status() == {"pending": 0, "scored": 2}

    model_nsfw_local.forget()
    assert model_nsfw_local.signal(same)["nsfw"] is True, "结果记在盘上:重启之后不再算"
    assert len(classifier) == 2


def test_等它的人等到的是写完盘之后_模拟重启不丢结果(classifier, tmp_path, monkeypatch) -> None:
    """此前队列一空线程就先「下班」再写盘:wait_idle 当它完事了,forget 清掉内存,那次写盘看到空的就不写 —— CI 上撞到过。"""
    slow = model_nsfw_local._flush  # noqa: SLF001
    flushing = threading.Event()

    def flush_after_a_while() -> None:
        flushing.set()
        time.sleep(0.3)
        slow()

    monkeypatch.setattr(model_nsfw_local, "_flush", flush_after_a_while)
    red = _original(tmp_path / "a", (210, 30, 40))
    model_nsfw_local.signal(red)
    assert flushing.wait(5), "算完了,开始写盘"
    assert model_nsfw_local.wait_idle()
    assert model_nsfw_local.scores_path().is_file(), "等完了盘上就有"
    model_nsfw_local.forget()
    assert model_nsfw_local.signal(red) == {"source": "local", "nsfw": True, "score": 0.93}


def test_权重没下就什么都不做_认不出的不说话(classifier, tmp_path, monkeypatch) -> None:
    picture = _original(tmp_path / "a", (210, 30, 40))
    nsfw_models.weights_path().unlink()
    assert model_nsfw_local.signal(picture) is None
    assert model_nsfw_local.status()["pending"] == 0 and not classifier, "没下权重:不排队"

    nsfw_models.weights_path().write_bytes(b"weights")
    monkeypatch.setattr(model_nsfw_local, "_probability", lambda _image: (_ for _ in ()).throw(OSError("broken")))
    model_nsfw_local.signal(picture)
    assert model_nsfw_local.wait_idle()
    assert model_nsfw_local.signal(picture) is None, "认不出:不当成「安全」,也不说是"
    assert model_nsfw_local.status() == {"pending": 0, "scored": 0}


def test_有原文件就看原文件_不看ComfyUI现转的有损那张_取不到才退回(classifier, tmp_path, monkeypatch) -> None:
    """沙盒实测:Big Buck Bunny 的兔脸特写,原 PNG 0.47、ComfyUI 预览接口现转的 WebP 0.69、宿主再缩的缩略图 0.78 ——
    一层层有损压缩把一张卡通特写推过了 0.5。这里用颜色替分数:缓存里那份(有损)偏红,原文件是绿的。"""
    from io import BytesIO

    from app.domain import model_previews

    lossy = _original(tmp_path / "lossy", (210, 30, 40))
    raw = BytesIO()
    Image.new("RGB", (64, 96), (30, 170, 60)).save(raw, "PNG")
    asked: list[str] = []

    def fetch(_instance, _route, url, headers):
        asked.append(url)
        assert headers == {"Authorization": "Bearer t"}, "原文件在那台服务器上:带它的头"
        return (raw.getvalue(), "image/png") if url.endswith("raw.png") else None

    monkeypatch.setattr(model_previews, "fetch_media", fetch)
    source = model_nsfw_local.Source(lossy.original, "image/webp", "i1", model_previews.Media(
        "http://comfy/pysssss/view/loras%2Fraw.png", {"Authorization": "Bearer t"}, True))
    model_nsfw_local.signal(source)
    assert model_nsfw_local.wait_idle()
    assert model_nsfw_local.signal(source) == {"source": "local", "nsfw": False, "score": 0.04}, "看的是原文件(绿的)"
    assert classifier == [(30, 170, 60)] and asked == ["http://comfy/pysssss/view/loras%2Fraw.png"]

    # 原文件取不到(那台机器上删了):退回缓存里那份,照样有结果
    other = _original(tmp_path / "other", (200, 20, 30))
    gone = model_nsfw_local.Source(other.original, "image/webp", "i1", model_previews.Media(
        "http://comfy/pysssss/view/loras%2Fgone.png", {"Authorization": "Bearer t"}, True))
    model_nsfw_local.signal(gone)
    assert model_nsfw_local.wait_idle()
    assert model_nsfw_local.signal(gone)["nsfw"] is True


def test_按缩略图记的老结果作废(classifier, tmp_path) -> None:
    """此前按缩略图(有损的那张)记的结果文件:读的时候删掉、重新算。"""
    old = nsfw_models.root() / f"scores-{nsfw_models.REVISION[:12]}.json"
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text('{"abc": 0.9}', encoding="utf-8")
    picture = _original(tmp_path / "a", (30, 170, 60))
    model_nsfw_local.signal(picture)
    assert model_nsfw_local.wait_idle()
    assert not old.exists()
    assert model_nsfw_local.scores_path().is_file() and model_nsfw_local.status()["scored"] == 1
