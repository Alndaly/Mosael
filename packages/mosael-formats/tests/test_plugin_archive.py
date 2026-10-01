"""插件包的安全检查:桌面端装包、社区上架都靠它挡恶意 zip。"""

from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from pathlib import Path

import pytest

from mosael_formats.plugin_archive import (
    ArchiveError,
    escapes_root,
    open_archive,
    read_plugin_archive,
    safe_extract,
)

MANIFEST = {
    "id": "dev.example.hello",
    "name": {"zh": "你好", "en": "Hello"},
    "version": "1.0.0",
    "permissions": ["network:example"],
    "runtime": {"kind": "process", "entry": "main.py"},
    "tools": {"declare": [{"name": "say_hello", "label": "Say hello", "effects": "none"}]},
}


def make_zip(files: dict[str, str | bytes], *, symlinks: dict[str, str] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
        for name, target in (symlinks or {}).items():
            info = zipfile.ZipInfo(name)
            info.external_attr = 0o120777 << 16
            archive.writestr(info, target)
    return buffer.getvalue()


def test_合格的包读得出清单和文件清单() -> None:
    data = make_zip({"mosael.plugin.json": json.dumps(MANIFEST), "main.py": "print('hi')\n"})
    package = read_plugin_archive(data)
    assert package.manifest.id == "dev.example.hello"
    assert package.manifest.permissions == ["network:example"]
    assert package.root == ""
    assert [one.path for one in package.files] == ["main.py", "mosael.plugin.json"]
    assert package.files[0].sha256 == hashlib.sha256(b"print('hi')\n").hexdigest()


def test_外面套一层目录的包认得出清单所在那一层() -> None:
    data = make_zip({
        "hello-main/mosael.plugin.json": json.dumps(MANIFEST),
        "hello-main/main.py": "x",
        "hello-main/examples/mosael.plugin.json": json.dumps({**MANIFEST, "id": "other"}),
    })
    package = read_plugin_archive(data)
    assert package.manifest.id == "dev.example.hello"
    assert package.root == "hello-main"
    assert "main.py" in [one.path for one in package.files]


@pytest.mark.parametrize(
    "name",
    ["../evil.py", "a/../../evil.py", "/etc/passwd", "..\\..\\evil.py", "C:/Windows/evil.dll", "c:evil"],
)
def test_越界路径一律拒绝(name: str) -> None:
    data = make_zip({"mosael.plugin.json": json.dumps(MANIFEST), name: "x"})
    with pytest.raises(ArchiveError) as caught:
        read_plugin_archive(data)
    assert caught.value.key == "pluginErr_archivePathEscape"


def test_包内的点点只要不出根就放行() -> None:
    assert not escapes_root("a/../b.txt")
    assert not escapes_root("./a/./b.txt")
    assert escapes_root("a/../../b.txt")


def test_符号链接拒绝() -> None:
    data = make_zip({"mosael.plugin.json": json.dumps(MANIFEST)}, symlinks={"link": "/etc"})
    with pytest.raises(ArchiveError) as caught:
        read_plugin_archive(data)
    assert caught.value.key == "pluginErr_archiveSymlink"


def test_解压炸弹按声明大小在解之前拒绝() -> None:
    data = make_zip({"mosael.plugin.json": json.dumps(MANIFEST), "big.bin": b"\0" * 50_000})
    assert len(data) < 5_000, "高压缩比才算炸弹"
    with pytest.raises(ArchiveError) as caught:
        read_plugin_archive(data, max_unpacked_bytes=10_000)
    assert caught.value.key == "pluginErr_archiveUnpackedTooLarge"


def test_压缩包本身超限() -> None:
    data = make_zip({"mosael.plugin.json": json.dumps(MANIFEST), "noise.bin": os.urandom(4000)})
    with pytest.raises(ArchiveError) as caught:
        read_plugin_archive(data, max_archive_bytes=1000)
    assert caught.value.key == "pluginErr_archiveTooLarge"


def test_文件太多() -> None:
    files = {"mosael.plugin.json": json.dumps(MANIFEST), **{f"f{i}.txt": "x" for i in range(20)}}
    with pytest.raises(ArchiveError) as caught:
        read_plugin_archive(make_zip(files), max_files=10)
    assert caught.value.key == "pluginErr_archiveTooManyFiles"


def test_不是_zip() -> None:
    with pytest.raises(ArchiveError) as caught:
        read_plugin_archive(b"PK\x03\x04 definitely not a zip")
    assert caught.value.key == "pluginErr_archiveNotZip"


def test_没有清单() -> None:
    with pytest.raises(ArchiveError) as caught:
        read_plugin_archive(make_zip({"readme.txt": "我不是插件"}))
    assert caught.value.key == "pluginErr_archiveNoManifest"


@pytest.mark.parametrize(
    "manifest",
    [
        "{not json",
        json.dumps(["not", "an", "object"]),
        json.dumps({"name": "缺 id", "version": "1.0.0"}),
        json.dumps({**MANIFEST, "id": "../../Documents"}),
        json.dumps({**MANIFEST, "instance": {"config": [{"key": "path", "label": "路径"}]}}),
        json.dumps({**MANIFEST, "tools": {"declare": [{"name": "x", "effects": "readonly"}]}}),
    ],
)
def test_清单不合法(manifest: str) -> None:
    with pytest.raises(ArchiveError) as caught:
        read_plugin_archive(make_zip({"mosael.plugin.json": manifest}))
    assert caught.value.key == "pluginErr_manifestInvalid"


def test_safe_extract_解到目标目录里面(tmp_path: Path) -> None:
    data = make_zip({"mosael.plugin.json": json.dumps(MANIFEST), "pkg/main.py": "x"})
    with open_archive(data) as archive:
        safe_extract(archive, tmp_path)
    assert (tmp_path / "pkg" / "main.py").read_text(encoding="utf-8") == "x"


def test_safe_extract_自己也查一遍(tmp_path: Path) -> None:
    """解压这一步不信任之前的任何检查。"""
    data = make_zip({"mosael.plugin.json": json.dumps(MANIFEST), "../escape.txt": "x"})
    with open_archive(data) as archive, pytest.raises(ArchiveError):
        safe_extract(archive, tmp_path / "inside")
    assert not (tmp_path / "escape.txt").exists()


def test_老写法的清单先升级再解析() -> None:
    """规则收紧(node.config 标了素材,input_schema 里也得是)之后,老包要能被升级链改合格,而不是装不上。"""
    old = {**MANIFEST, "manifest_version": 4, "tools": {"declare": [{
        "name": "t", "input_schema": {"type": "object", "properties": {"img": {"type": "string"}}},
        "node": {"config": {"img": {"type": "template", "format": "asset"}}}}]}}
    package = read_plugin_archive(make_zip({"mosael.plugin.json": json.dumps(old), "main.py": "x"}))
    assert "format" not in package.raw["tools"]["declare"][0]["node"]["config"]["img"]
    assert package.manifest.declared_tools[0]["name"] == "t"
