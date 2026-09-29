"""装插件就是往这台机器上放一份会被执行的代码:索引和包只从 https 拿,包要和索引登记的 sha256 对得上。

此前索引与下载地址都收 `http://`,路上任何一个人都能把包换掉;发版索引里也没有摘要,下载地址被换、
CDN 给错了文件都照样装。现在:明文 http 只认本机回环(开发用),发版索引写上每个包的 sha256
(scripts/sync-plugin-registry.py),从市场装时交回这个值,下载后核对,对不上不装。
"""

from __future__ import annotations

import hashlib

import pytest

from app.domain.plugins import registry as market
from app.domain.plugins.errors import PluginDomainError


@pytest.mark.parametrize(("url", "ok"), [
    ("https://github.com/o/r/releases/download/v1/x.zip", True),
    ("http://127.0.0.1:8765/registry.json", True),
    ("http://localhost/x.zip", True),
    ("http://github.com/o/r/releases/download/v1/x.zip", False),
    ("http://evil.example/x.zip", False),
    ("ftp://example.com/x.zip", False),
    ("file:///etc/passwd", False),
    ("https:///no-host", False),
])
def test_只认_https_明文只给本机回环(url: str, ok: bool) -> None:
    assert market.secure_url(url) is ok


def test_明文地址下载和拉索引都当场拒() -> None:
    with pytest.raises(PluginDomainError) as refused:
        market.download_archive("http://mirror.example/x.zip")
    assert refused.value.key == "pluginErr_downloadBadScheme"
    with pytest.raises(PluginDomainError) as refused:
        market.fetch_index("http://mirror.example/registry.json")
    assert refused.value.key == "pluginErr_marketBadScheme"


def test_摘要对不上不装_没给摘要不核对(monkeypatch) -> None:
    data = b"PK\x03\x04 a plugin"
    monkeypatch.setattr(market, "_download", lambda url: data)
    good = hashlib.sha256(data).hexdigest()
    assert market.download_archive("https://x/y.zip", sha256=good) == data
    assert market.download_archive("https://x/y.zip", sha256=good.upper()) == data
    assert market.download_archive("https://x/y.zip") == data, "从链接装、老索引:没有摘要可核对"
    with pytest.raises(PluginDomainError) as refused:
        market.download_archive("https://x/y.zip", sha256="0" * 64)
    assert refused.value.key == "pluginErr_archiveDigestMismatch"


def test_安装接口把摘要交给下载(monkeypatch) -> None:
    from tests.util import fresh_client

    client = fresh_client()
    seen: dict = {}

    def fake(url: str, *, sha256: str = "") -> bytes:
        seen.update(url=url, sha256=sha256)
        raise PluginDomainError("pluginErr_archiveDigestMismatch")

    monkeypatch.setattr(market, "download_archive", fake)
    digest = "a" * 64
    res = client.post("/api/plugins/install", json={"url": "https://x/y.zip", "sha256": digest})
    assert res.status_code >= 400 and seen == {"url": "https://x/y.zip", "sha256": digest}
    assert client.post("/api/plugins/install", json={"url": "https://x/y.zip", "sha256": "not-hex"}).status_code == 422
