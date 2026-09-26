"""应用里的插件市场装的索引是**发版产物**:和插件包同一次发版、同一份源码,许的就是给的。

此前应用读官网上由 main 生成的那份,下载地址却是最新一次 Release 的附件。main 上改了插件版本、
还没发版的那段时间里,索引许 0.2.0、下载给 0.1.0:「更新」装回旧版,「有新版」永远不消失
(Remotion、Manim、文本工具……一起中招)。现在:

- scripts/sync-plugin-registry.py 一个生成器出两份:官网那份(main)和发版那份(--release);
  条目除了下载地址一模一样;
- 发版那份的下载地址钉在生成它的 tag 上,生成时逐个打开包核对 id 与版本,对不上就让发版失败;
- release.yml 在打完插件包之后生成它,和插件包一起传到那次 Release。
"""

from __future__ import annotations

import importlib.util
import io
import json
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "sync-plugin-registry.py"


@pytest.fixture(scope="module")
def generator():
    spec = importlib.util.spec_from_file_location("sync_plugin_registry", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _without_download(index: dict) -> list[dict]:
    return [{key: value for key, value in one.items() if key != "download"} for one in index["plugins"]]


def _pack(packages: Path, index: dict, **versions: str) -> None:
    """照 release.yml 那样把每个要从市场装的插件打成 <id>.zip(清单在包的根上)。"""
    packages.mkdir(parents=True, exist_ok=True)
    for one in index["plugins"]:
        if one["bundled"]:
            continue
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            manifest = {"id": one["id"], "version": versions.get(one["id"], one["version"])}
            archive.writestr("mosael.plugin.json", json.dumps(manifest))
        (packages / f"{one['id']}.zip").write_bytes(buffer.getvalue())


def test_两份产物的条目除了下载地址一模一样(generator) -> None:
    website = generator.website_index()
    release = generator.release_index("v1.5.3", "Alndaly/Mosael")
    assert _without_download(website) == _without_download(release)
    assert website["channel"] == "main" and release["channel"] == "release" and release["release"] == "v1.5.3"


def test_官网那份就是仓库里提交的那份(generator) -> None:
    committed = json.loads((ROOT / "website" / "public" / "plugins" / "registry.json").read_text(encoding="utf-8"))
    assert committed == generator.website_index(), "跑一下 python3 scripts/sync-plugin-registry.py"


def test_发版那份的下载地址钉在这次发版的_tag_上(generator) -> None:
    """读索引的那一刻恰好发了新版,拿到的也是「那一版的索引 + 那一版的包」。"""
    release = generator.release_index("v1.5.3", "Alndaly/Mosael")
    for one in release["plugins"]:
        if one["bundled"]:
            assert one["download"] == "", f"{one['id']} 是内置的,不从市场装"
        else:
            assert one["download"] == f"https://github.com/Alndaly/Mosael/releases/download/v1.5.3/{one['id']}.zip"


@pytest.mark.parametrize("tag", ["main", "1.5.3", "v1.5", "refs/tags/v1.5.3"])
def test_只认发版的_tag(generator, tag: str) -> None:
    with pytest.raises(SystemExit):
        generator.release_index(tag)


def test_核对过的包才写索引(generator, tmp_path) -> None:
    packages = tmp_path / "dist" / "plugins"
    _pack(packages, generator.release_index("v1.5.3"))
    generator.main(["--release", "v1.5.3", "--repo", "Alndaly/Mosael", "--packages", str(packages)])
    written = json.loads((packages / "registry.json").read_text(encoding="utf-8"))
    assert written == generator.release_index("v1.5.3", "Alndaly/Mosael")


def test_包里的版本和索引对不上_发版失败(generator, tmp_path) -> None:
    """这正是用户撞到的那件事:索引许 0.2.0,包里是 0.1.0。在发版时就拦下,而不是在用户机器上。"""
    index = generator.release_index("v1.5.3")
    remotion = next(one["id"] for one in index["plugins"] if one["id"].endswith(".remotion"))
    packages = tmp_path / "plugins"
    _pack(packages, index, **{remotion: "0.0.1"})
    with pytest.raises(SystemExit, match=remotion):
        generator.verify_packages(index, packages)
    assert not (packages / "registry.json").exists()


def test_少了包或多了包_发版失败(generator, tmp_path) -> None:
    index = generator.release_index("v1.5.3")
    packages = tmp_path / "plugins"
    _pack(packages, index)
    missing = next(one["id"] for one in index["plugins"] if not one["bundled"])
    (packages / f"{missing}.zip").unlink()
    (packages / "dev.stray.zip").write_bytes((packages / next(packages.glob("*.zip")).name).read_bytes())
    with pytest.raises(SystemExit) as caught:
        generator.verify_packages(index, packages)
    assert missing in str(caught.value) and "dev.stray" in str(caught.value)


def test_发版流程生成它并和插件包一起上传() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    package_step = workflow[workflow.index("- name: Package plugins") : workflow.index("- name: Upload plugins to release")]
    assert (
        'python3 scripts/sync-plugin-registry.py --release "$GITHUB_REF_NAME" --repo "$GITHUB_REPOSITORY" '
        "--packages dist/plugins" in package_step
    ), "索引要在打完插件包之后、由同一个生成器按这次的 tag 生成"
    assert package_step.index("zip -qr") < package_step.index("sync-plugin-registry.py"), "先打包,再核对着生成索引"
    assert "dist/plugins/*.zip dist/plugins/registry.json" in workflow, "索引要和插件包传到同一次 Release"


def test_应用默认读的就是发版附带的那份() -> None:
    from app.api.routes.plugins import DEFAULT_REGISTRY_URL

    assert DEFAULT_REGISTRY_URL.endswith("/releases/latest/download/registry.json")
