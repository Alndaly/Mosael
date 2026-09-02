"""插件市场:浏览、预览、安装。

此前装插件的唯一办法是手动把文件夹丢进插件目录再点扫描。对写插件的人没问题,对用它的人
是道墙 —— 而插件的价值恰恰在于用的人比写的人多得多。

**装插件 = 在用户机器上放一份会被执行的代码。** 所以这里的重点不是"能不能装上",而是
装的过程挡住了什么:压缩包里的路径穿越、符号链接、解压炸弹、没有清单的垃圾包、以及
悄悄覆盖一个已经装好并填了凭据的包。挡不住的是「这个作者是不是好人」—— 那件事只能由
用户看着权限清单自己决定,所以那份清单必须在装之前就看得见(preview)。
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins import registry as market

MANIFEST = {
    "id": "dev.test.demo",
    "name": "演示",
    "version": "1.0.0",
    "runtime": {"kind": "process", "entry": "main.py"},
    "permissions": ["network:demo"],
    "tools": {"expose": "all", "declare": [{"name": "go", "description": "跑一下"}]},
}


def make_zip(files: dict[str, str], *, prefix: str = "") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, body in files.items():
            archive.writestr(f"{prefix}{name}", body)
    return buffer.getvalue()


def good_zip(prefix: str = "", manifest: dict | None = None) -> bytes:
    return make_zip(
        {
            "mosael.plugin.json": json.dumps(manifest or MANIFEST, ensure_ascii=False),
            "main.py": "print('{}')",
        },
        prefix=prefix,
    )


class Test装得上:
    def test_平铺的包(self, tmp_path) -> None:
        raw = market.install_archive(good_zip(), tmp_path)
        assert raw["id"] == "dev.test.demo"
        assert (tmp_path / "dev.test.demo" / "mosael.plugin.json").is_file()
        assert (tmp_path / "dev.test.demo" / "main.py").is_file()

    def test_GitHub_那种外面套一层的包(self, tmp_path) -> None:
        """从 GitHub 下下来的 zip 外面总套一层 `repo-main/`,而清单在里面。
        认死最外层的话,从 GitHub 下的包一个都装不上 —— 而那正是最常见的来源。"""
        market.install_archive(good_zip(prefix="my-plugin-main/"), tmp_path)
        assert (tmp_path / "dev.test.demo" / "main.py").is_file()

    def test_目录名用插件_id_而不是压缩包名(self, tmp_path) -> None:
        """用压缩包名的话,同一个插件从两个地方下下来会装成两份。"""
        market.install_archive(good_zip(prefix="随便什么名字/"), tmp_path)
        assert [p.name for p in tmp_path.iterdir()] == ["dev.test.demo"]


class Test挡住的东西:
    def test_路径穿越(self, tmp_path) -> None:
        """zip 里的路径是压缩包作者写的字符串,可以是 ../../.ssh/authorized_keys。"""
        data = make_zip(
            {"mosael.plugin.json": json.dumps(MANIFEST), "../../跑出去了.txt": "x"}
        )
        with pytest.raises(PluginDomainError, match="越界路径"):
            market.install_archive(data, tmp_path)
        assert not (tmp_path.parent.parent / "跑出去了.txt").exists()

    def test_符号链接(self, tmp_path) -> None:
        """extractall 自 3.6 起会规范化 `..`,但**不拦符号链接** —— 一个指向 /etc 的链接
        解出来之后,后面任何按相对路径写文件的动作都会写到那儿去。"""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("mosael.plugin.json", json.dumps(MANIFEST))
            info = zipfile.ZipInfo("link")
            info.external_attr = (0o120777 << 16)  # S_IFLNK
            archive.writestr(info, "/etc")
        with pytest.raises(PluginDomainError, match="符号链接"):
            market.install_archive(buffer.getvalue(), tmp_path)

    def test_解压炸弹(self, tmp_path, monkeypatch) -> None:
        """一个 1MB 的 zip 能解出几十 GB。上限查的是**声明的解压后大小**,在解之前。"""
        monkeypatch.setattr(market, "MAX_UNPACKED_BYTES", 100)
        data = make_zip({"mosael.plugin.json": json.dumps(MANIFEST), "big.txt": "x" * 5000})
        with pytest.raises(PluginDomainError, match="解压后超过"):
            market.install_archive(data, tmp_path)

    def test_没有清单的包(self, tmp_path) -> None:
        data = make_zip({"readme.txt": "我不是插件"})
        with pytest.raises(PluginDomainError, match="不是一个插件"):
            market.install_archive(data, tmp_path)
        assert list(tmp_path.iterdir()) == [], "垃圾包在插件目录里留下了东西"

    def test_清单不合法的包(self, tmp_path) -> None:
        """先看清楚再落地 —— 不合法的包不该在插件目录里留下任何东西。"""
        data = make_zip({"mosael.plugin.json": json.dumps({"name": "缺 id"})})
        with pytest.raises(PluginDomainError, match="清单不合法"):
            market.install_archive(data, tmp_path)
        assert list(tmp_path.iterdir()) == []

    def test_不是_zip(self, tmp_path) -> None:
        with pytest.raises(PluginDomainError, match="合法的 zip"):
            market.install_archive(b"not a zip at all", tmp_path)


class Test不悄悄覆盖:
    def test_装过了就拒绝(self, tmp_path) -> None:
        """那个目录里可能已经有用户填过的东西,而且新版本可能声明了完全不同的权限。"""
        market.install_archive(good_zip(), tmp_path)
        with pytest.raises(PluginDomainError, match="已经装过"):
            market.install_archive(good_zip(), tmp_path)

    def test_明确要求覆盖才覆盖(self, tmp_path) -> None:
        market.install_archive(good_zip(), tmp_path)
        newer = {**MANIFEST, "version": "2.0.0"}
        raw = market.install_archive(good_zip(manifest=newer), tmp_path, overwrite=True)
        assert raw["version"] == "2.0.0"

    def test_覆盖时旧文件不残留(self, tmp_path) -> None:
        """留着的话,一个上个版本才有的脚本会一直躺在那儿 —— 而清单已经不提它了。"""
        market.install_archive(make_zip({"mosael.plugin.json": json.dumps(MANIFEST), "旧脚本.py": "x"}), tmp_path)
        assert (tmp_path / "dev.test.demo" / "旧脚本.py").is_file()
        market.install_archive(good_zip(), tmp_path, overwrite=True)
        assert not (tmp_path / "dev.test.demo" / "旧脚本.py").exists()


class Test索引:
    def test_只认_http(self) -> None:
        with pytest.raises(PluginDomainError, match="http"):
            market.fetch_index("file:///etc/passwd")

    def test_两种形状都认(self, monkeypatch) -> None:
        """{"plugins": [...]} 和裸数组 —— 后者是最省事的写法,没理由不认。"""
        for payload in ({"plugins": [{"id": "a"}]}, [{"id": "a"}]):
            monkeypatch.setattr(market, "RetryingClient", _fake_client(payload))
            assert market.fetch_index("https://e/r.json") == [{"id": "a"}]

    def test_没有_id_的条目丢掉(self, monkeypatch) -> None:
        """没有 id 就没法判断装没装过,也没法装 —— 显示出来只会让人点了没反应。"""
        monkeypatch.setattr(market, "RetryingClient", _fake_client({"plugins": [{"id": "a"}, {"name": "没 id"}]}))
        assert market.fetch_index("https://e/r.json") == [{"id": "a"}]

    def test_格式不对说得明白(self, monkeypatch) -> None:
        monkeypatch.setattr(market, "RetryingClient", _fake_client({"随便": 1}))
        with pytest.raises(PluginDomainError, match="格式不对"):
            market.fetch_index("https://e/r.json")


def _fake_client(payload):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    class FakeClient:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            return FakeResponse()

    return FakeClient
