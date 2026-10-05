"""本机识别 NSFW 预览图(ADR 0038 §9「本地识别怎么带」):权重怎么下、识别怎么排队、结果怎么记。

和模型库连起来的那一段(列的时候带上、看显示着的那张)在 test_plugin_model_library 里。
"""

from __future__ import annotations

import hashlib
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from PIL import Image

from app.ai.runtime import nsfw_models
from app.domain import model_nsfw_local
from tests.util import fresh_client, second_client


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
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()


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


def _thumbnail(path: Path, color: tuple[int, int, int]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 96), color).save(path, "WEBP")
    return path


@pytest.fixture
def classifier(monkeypatch):
    """权重「下好了」(正式位置上有个文件),识别换成看颜色:偏红的算 NSFW。记下每次识别的是哪张。"""
    path = nsfw_models.weights_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"weights")
    seen: list[str] = []

    def probability(thumbnail: Path) -> float:
        seen.append(thumbnail.name)
        with Image.open(thumbnail) as image:
            red, green, _blue = image.convert("RGB").getpixel((8, 8))
        return 0.93 if red > 150 and green < 100 else 0.04

    monkeypatch.setattr(model_nsfw_local, "_probability", probability)
    return seen


def test_没算过的排进队_下次就有_按图的内容记_重启之后从盘上读(classifier, tmp_path) -> None:
    red = _thumbnail(tmp_path / "a.thumbnail.webp", (210, 30, 40))
    same = tmp_path / "b.thumbnail.webp"
    same.write_bytes(red.read_bytes())
    green = _thumbnail(tmp_path / "c.thumbnail.webp", (30, 170, 60))

    assert model_nsfw_local.signal(red) is None, "列的时候不等它"
    model_nsfw_local.signal(same)
    model_nsfw_local.signal(green)
    assert model_nsfw_local.wait_idle()
    assert model_nsfw_local.signal(red) == {"source": "local", "nsfw": True, "score": 0.93}
    assert model_nsfw_local.signal(same) == {"source": "local", "nsfw": True, "score": 0.93}, "同一张图换了名字不再算"
    assert model_nsfw_local.signal(green) == {"source": "local", "nsfw": False, "score": 0.04}
    assert sorted(classifier) == ["a.thumbnail.webp", "c.thumbnail.webp"]
    assert model_nsfw_local.status() == {"pending": 0, "scored": 2}

    model_nsfw_local.forget()
    assert model_nsfw_local.signal(same)["nsfw"] is True, "结果记在盘上:重启之后不再算"
    assert len(classifier) == 2


def test_权重没下就什么都不做_认不出的不说话(classifier, tmp_path, monkeypatch) -> None:
    picture = _thumbnail(tmp_path / "a.thumbnail.webp", (210, 30, 40))
    nsfw_models.weights_path().unlink()
    assert model_nsfw_local.signal(picture) is None
    assert model_nsfw_local.status()["pending"] == 0 and not classifier, "没下权重:不排队"

    nsfw_models.weights_path().write_bytes(b"weights")
    monkeypatch.setattr(model_nsfw_local, "_probability", lambda _path: (_ for _ in ()).throw(OSError("broken")))
    model_nsfw_local.signal(picture)
    assert model_nsfw_local.wait_idle()
    assert model_nsfw_local.signal(picture) is None, "认不出:不当成「安全」,也不说是"
    assert model_nsfw_local.status() == {"pending": 0, "scored": 0}
