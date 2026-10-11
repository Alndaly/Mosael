"""让 Mosael 自己把带 libass 的完整版 ffmpeg 装上(维护者:「不该让用户必须自行在别处下载」)。

这一组钉的是**装上的判据**,不是下载本身:

- 清单里这台机器对应哪一条(macOS / Linux 是两个包、Windows 一个包;架构名归一:`AMD64`/`aarch64`);
- 摘要对不上:一个字节都不落地、不写配置;
- 装上了却没有 libass:照样算没装成(带字幕的导出仍旧做不了),不写配置;
- 装成了:两个可执行文件都在、真的跑得起来(`ffmpeg -version`)、`-filters` 里有 subtitles,
  最后把路径写进「管理 → 引擎 → FFmpeg」那一格(media_tools 的同一个接缝,不另开一套);
- 这个平台没有对得上的构建:起任务之前就说,不留一个注定失败的任务。

假的可执行文件是真的 shell 脚本,校验走的是真的 `-version` / `-filters` 探测(见 test_ffmpeg_path_is_a_setting),
不把探测本身换成桩 —— 否则"装上了"这件事就没人验了。
"""

from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path

import pytest

from app.core.db import SessionLocal
from app.db.models import Job, MediaToolsConfig
from app.domain import media_tools, media_tools_install
from app.domain.jobs import wait_for_idle_jobs
from app.media import render_executor
from tests.util import fresh_client

LIBASS_LINE = " ..C subtitles         V->V       Render text subtitles onto input video using the libass library."
PLAIN_LINE = " ..C scale             V->V       Scale the input video size."
TARGET = "linux-x86_64"


def _fake_binary(path: Path, *, filters: str = LIBASS_LINE, version: str = "9.9.9-test") -> bytes:
    """一个真的能跑的可执行文件:只回答 `-version` 和 `-filters` 两问。"""
    path.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        f'  *-version*) printf %s {json.dumps(f"ffmpeg version {version} Copyright (c) 2000-2026 the FFmpeg developers\\n")} ;;\n'
        f'  *-filters*) printf %s {json.dumps(filters + chr(10))} ;;\n'
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path.read_bytes()


def _archive(path: Path, members: dict[str, bytes], *, prefix: str = "") -> tuple[Path, str]:
    """打一个包,返回 (路径, sha256)。`prefix` 非空时成员都在那一层目录下(Windows 包的形状)。"""
    with zipfile.ZipFile(path, "w") as bundle:
        for name, data in members.items():
            info = zipfile.ZipInfo(f"{prefix}{name}" if prefix else name)
            #: 权限位故意留成 644:zipfile 本来就不还原它,验的就是"解完自己补 +x"这一步。
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            bundle.writestr(info, data)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def rig(monkeypatch, tmp_path: Path):
    """把清单、下载、装到哪儿三处换成本用例自己的,其余(校验、任务、写配置)全走真的。"""
    def use(targets: dict, files: dict[str, Path] | None = None) -> None:
        manifest = tmp_path / "media_tool_builds.json"
        manifest.write_text(json.dumps({"targets": targets}), encoding="utf-8")
        monkeypatch.setattr(media_tools_install, "MANIFEST_PATH", manifest)
        monkeypatch.setattr(media_tools_install, "target_key", lambda *a, **k: TARGET)
        monkeypatch.setattr(media_tools_install, "scratch_dir", lambda purpose: _dir(tmp_path / "work"))
        monkeypatch.setattr(media_tools_install, "install_dir", lambda version: tmp_path / "tools" / version)
        monkeypatch.setattr(media_tools_install, "secure_url", lambda url: True)
        if files is not None:
            def download(job_id, url, target, sha256, index, count):  # noqa: ANN001 — 和被测函数同形
                target.write_bytes(files[url].read_bytes())
                if sha256 and hashlib.sha256(target.read_bytes()).hexdigest() != sha256:
                    raise media_tools_install.MediaToolError("mediaToolErr_digestMismatch", name=target.name)
                media_tools_install._progress(job_id, 0.4, "jobMsg_mediaToolDownloading")  # noqa: SLF001

            monkeypatch.setattr(media_tools_install, "_download", download)
        render_executor.ffmpeg_has_libass.cache_clear()

    return use


def _dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _install(client, workspace_id: str) -> tuple[int, dict]:
    response = client.post("/api/settings/ffmpeg/install", json={"workspace_id": workspace_id})
    return response.status_code, (response.json() if response.headers.get("content-type", "").startswith("application/json") else {})


def _start(client) -> tuple[str, str]:
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    status, body = _install(client, workspace_id)
    assert status == 200, body
    return body["id"], workspace_id


def _finished(job_id: str) -> Job:
    assert wait_for_idle_jobs(timeout=60), "安装任务没在超时内跑完"
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job is not None
        db.expunge(job)
        return job


def test_清单按平台认_架构名归一() -> None:
    assert media_tools_install.target_key("darwin", "arm64") == "darwin-arm64"
    assert media_tools_install.target_key("darwin", "x86_64") == "darwin-x86_64"
    assert media_tools_install.target_key("win32", "AMD64") == "win32-x86_64"
    assert media_tools_install.target_key("linux", "aarch64") == "linux-arm64"
    chosen = media_tools_install.plan("freebsd", "x86_64")
    assert chosen.available is False and chosen.reason == "mediaToolErr_noBuild" and chosen.detail


def test_装成了_路径写进那一格而且真的能烧字(rig, tmp_path: Path) -> None:
    ffmpeg_zip, ffmpeg_sha = _archive(tmp_path / "ffmpeg.zip", {"ffmpeg": _fake_binary(tmp_path / "src-ffmpeg")})
    ffprobe_zip, ffprobe_sha = _archive(tmp_path / "ffprobe.zip", {"ffprobe": _fake_binary(tmp_path / "src-ffprobe")})
    rig({TARGET: {"version": "9.9.9", "archives": [{"url": "https://example.test/f.zip", "sha256": ffmpeg_sha},
                                                   {"url": "https://example.test/p.zip", "sha256": ffprobe_sha}],
                  "binaries": {"ffmpeg": "ffmpeg", "ffprobe": "ffprobe"}}},
        {"https://example.test/f.zip": ffmpeg_zip, "https://example.test/p.zip": ffprobe_zip})

    client = fresh_client()
    job_id, _workspace_id = _start(client)
    job = _finished(job_id)

    assert job.status == "succeeded", job.message
    with SessionLocal() as db:
        saved = db.get(MediaToolsConfig, media_tools.SINGLETON_ID)
        assert saved is not None and saved.ffmpeg_path.endswith("tools/9.9.9/ffmpeg")
        installed = Path(saved.ffmpeg_path)
    assert installed.is_file()
    assert installed.stat().st_mode & stat.S_IXUSR, "解出来的可执行文件要自己补上可执行位"
    assert (installed.parent / "ffprobe").is_file(), "ffprobe 也一起装上(旁边那个才认)"
    assert media_tools.version_of(str(installed)) == "9.9.9-test", "跑得起来才算装上"
    assert render_executor.ffmpeg_has_libass(str(installed)) is True, "能烧字才算装上"
    #: 界面上那一格也该照着说(同一个接缝,没有第二份真相)。
    assert Path(client.get("/api/settings/ffmpeg").json()["path"]) == installed


def test_摘要对不上_一个字节都不落地也不写配置(rig, tmp_path: Path) -> None:
    archive, _sha = _archive(tmp_path / "ffmpeg.zip", {"ffmpeg": _fake_binary(tmp_path / "src-ffmpeg")})
    rig({TARGET: {"version": "1.0.0", "archives": [{"url": "https://example.test/f.zip", "sha256": "0" * 64}],
                  "binaries": {"ffmpeg": "ffmpeg", "ffprobe": "ffprobe"}}},
        {"https://example.test/f.zip": archive})

    client = fresh_client()
    job_id, _workspace_id = _start(client)
    job = _finished(job_id)

    assert job.status == "failed"
    assert "sha256" in (job.error or ""), job.error
    with SessionLocal() as db:
        assert db.get(MediaToolsConfig, media_tools.SINGLETON_ID) is None, "没验过就不该写配置"
    assert not list((tmp_path / "tools").rglob("ffmpeg")), "一个字节都不落地"


def test_装上了却没有libass_照样算没装成(rig, tmp_path: Path) -> None:
    ffmpeg_zip, ffmpeg_sha = _archive(tmp_path / "f.zip",
                                      {"ffmpeg": _fake_binary(tmp_path / "plain-ffmpeg", filters=PLAIN_LINE)})
    ffprobe_zip, ffprobe_sha = _archive(tmp_path / "p.zip", {"ffprobe": _fake_binary(tmp_path / "plain-ffprobe")})
    rig({TARGET: {"version": "2.0.0", "archives": [{"url": "https://example.test/f.zip", "sha256": ffmpeg_sha},
                                                   {"url": "https://example.test/p.zip", "sha256": ffprobe_sha}],
                  "binaries": {"ffmpeg": "ffmpeg", "ffprobe": "ffprobe"}}},
        {"https://example.test/f.zip": ffmpeg_zip, "https://example.test/p.zip": ffprobe_zip})

    client = fresh_client()
    job_id, _workspace_id = _start(client)
    job = _finished(job_id)

    assert job.status == "failed"
    assert "libass" in (job.error or ""), job.error
    with SessionLocal() as db:
        assert db.get(MediaToolsConfig, media_tools.SINGLETON_ID) is None, "不能烧字的那个不该被设成在用的"


def test_一个包里两个可执行文件且多一层目录_windows的形状(rig, tmp_path: Path) -> None:
    """Windows 的包和 macOS / Linux 不一样:一个 zip、里面 `bin/ffmpeg.exe` 与 `bin/ffprobe.exe`,
    而且多一层根目录。解包要剥掉那一层,并按清单说的路径去认那两个文件。"""
    binary = _fake_binary(tmp_path / "src-exe")
    archive, sha = _archive(tmp_path / "win.zip", {"bin/ffmpeg.exe": binary, "bin/ffprobe.exe": binary},
                            prefix="ffmpeg-n9.0-win64-gpl/")
    rig({TARGET: {"version": "autobuild-test", "archives": [{"url": "https://example.test/win.zip", "sha256": sha}],
                  "binaries": {"ffmpeg": "bin/ffmpeg.exe", "ffprobe": "bin/ffprobe.exe"}}},
        {"https://example.test/win.zip": archive})

    client = fresh_client()
    job_id, _workspace_id = _start(client)
    job = _finished(job_id)

    assert job.status == "succeeded", job.message
    with SessionLocal() as db:
        saved = db.get(MediaToolsConfig, media_tools.SINGLETON_ID)
        assert saved is not None
        installed = Path(saved.ffmpeg_path)
    assert installed.name == "ffmpeg.exe" and installed.parent.name == "bin", "那一层根目录剥掉了"
    assert (installed.parent / "ffprobe.exe").is_file()


def test_这个平台没有对得上的构建_起任务之前就说(rig, tmp_path: Path) -> None:
    rig({})
    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    status, body = _install(client, workspace_id)
    assert status == 422, body
    assert body["detail"], "要说清是哪一种装不了"
