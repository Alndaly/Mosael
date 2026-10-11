"""把「带 libass 的完整版 ffmpeg」装到 Mosael 自己的目录里。

维护者:「Mosael 不具备主动下载 ffmpeg-full 的能力,应该补充这部分能力,否则用户必须自行在别处下载」。

## 装什么、从哪来

清单在 `media_tool_builds.json`(由 `scripts/sync-ffmpeg-builds.py` 生成):每个平台一份**钉死**的构建,
带 sha256。两个来源,因为各平台能拿到的静态构建不一样:

- **macOS / Linux**:<https://ffmpeg.martin-riedl.de> 的发行构建 —— **两个包**(`ffmpeg.zip`、`ffprobe.zip`),
  解出来就是可执行文件本身;
- **Windows**:<https://github.com/BtbN/FFmpeg-Builds> 按日期打标签的 release —— **一个包**,
  里面 `bin/ffmpeg.exe` 与 `bin/ffprobe.exe`,而且多一层根目录。

## 「下载完了没有」各按各的判

两边都先核对 sha256(**对不上一个字节都不落地**),再确认那个可执行文件真的在、真的跑得起来 ——
而"真的跑得起来"在两边不是一件事:macOS / Linux 上还要有**可执行位**(`zipfile` 不还原权限位,
得自己 chmod),Windows 上看的是 `.exe` 在不在。最后一关是**能不能烧字**(`ffmpeg_has_libass`):
装上一个没有 libass 的 ffmpeg 等于没装 —— 带字幕的导出照样被拒。三者缺一都不算装上,也不写配置。

## 装到哪儿、怎么生效

`<数据目录>/tools/ffmpeg/<版本>/`(Mosael 自己的目录,不往系统里塞东西),装完把 ffmpeg 的路径写进
`MediaToolsConfig` —— 就是「管理 → 引擎 → FFmpeg」那一格填的同一个位置(`domain/media_tools.save_path`),
所以生效、重探、界面上显示的都是既有那一条路,不另开一套。

一次安装是一个任务(`media_tool_install`):任务中心里看得见、能停(下载走 `RetryingClient`,
取消时正在进行的请求会被掐掉,见 core/abort)。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import shutil
import stat
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.http_retry import RetryingClient
from app.core.i18n import LocalizedError
from app.core.unit_of_work import unit_of_work
from app.db.models import Job
from app.domain import media_tools
from app.domain.jobs import blame, create_job, dispatch_job, emit_job_event, finish_job, say
from app.domain.plugins.registry import secure_url
from app.media.scratch import scratch_dir

logger = logging.getLogger(__name__)

#: 暂存目录的用途名(见 media/scratch):下载和解包都在它底下,进程中途没了下次启动清掉。
SCRATCH = "media-tool-install"

MANIFEST_PATH = Path(__file__).resolve().with_name("media_tool_builds.json")

#: 下载超时:一个 30–80 MB 的包,给的比插件包宽松得多。
DOWNLOAD_TIMEOUT_SECONDS = 600.0
#: 解包后允许占用多大(解出来 60–140 MB,留足余量)。
MAX_UNPACKED_BYTES = 600 * 1024 * 1024


class MediaToolError(LocalizedError):
    """装不上(这个平台没有构建、摘要对不上、解不出来、装上了却烧不了字)。key 说是哪一种。"""


@dataclass(frozen=True)
class InstallPlan:
    """这台机器上能装什么:清单里对应哪一条、什么版本、能不能装(不能就带一句为什么)。"""

    target: str
    version: str
    archives: int
    #: 不能装时的文案 key(`mediaToolErr_*`);能装时为空。
    reason: str = ""
    #: 清单里没有这个平台,或者清单本身没带上。
    detail: str = ""

    @property
    def available(self) -> bool:
        return not self.reason


def _machine(machine: str) -> str:
    """把各家报的架构名归一:`AMD64` / `x86_64` → `x86_64`;`arm64` / `aarch64` → `arm64`。"""
    lowered = (machine or "").lower()
    if lowered in ("amd64", "x86_64", "x64", "i386", "i686"):
        return "x86_64"
    if lowered in ("arm64", "aarch64"):
        return "arm64"
    return lowered


def target_key(platform_name: str | None = None, machine: str | None = None) -> str:
    """清单里的键:`<sys.platform>-<架构>`(darwin-arm64、win32-x86_64、linux-arm64……)。"""
    return f"{platform_name or sys.platform}-{_machine(machine or platform.machine())}"


def manifest() -> dict[str, Any]:
    """清单。读不到(没随包带上)就当没有可用构建 —— 界面上照实说,不假装能装。"""
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("ffmpeg 构建清单读不到:%s", MANIFEST_PATH)
        return {}


def plan(platform_name: str | None = None, machine: str | None = None) -> InstallPlan:
    """这台机器上装哪个构建。**不联网** —— 清单是发版时钉好的。"""
    key = target_key(platform_name, machine)
    entry = (manifest().get("targets") or {}).get(key)
    if not isinstance(entry, dict) or not entry.get("archives"):
        return InstallPlan(target=key, version="", archives=0, reason="mediaToolErr_noBuild",
                           detail=f"{sys.platform}/{platform.machine()}")
    return InstallPlan(target=key, version=str(entry.get("version") or ""), archives=len(entry["archives"]))


def install_dir(version: str) -> Path:
    """装到哪儿:`<数据目录>/tools/ffmpeg/<版本>/`。同一个版本重复装就换掉那一份。"""
    return settings.data_dir / "tools" / "ffmpeg" / (version or "unknown")


def installed_binaries(version: str, entry: dict[str, Any]) -> tuple[Path, Path] | None:
    """已经装好的那一份在哪(ffmpeg, ffprobe)。没装全就是 None —— 调用方据此决定要不要装。"""
    where = install_dir(version)
    wanted = entry.get("binaries") or {}
    paths = [where / str(wanted.get(name) or name) for name in ("ffmpeg", "ffprobe")]
    return (paths[0], paths[1]) if all(one.is_file() for one in paths) else None


def already_installed() -> tuple[Path, Path] | None:
    """当前清单这一版已经装好了吗(装好就直接用它,不再下一次)。"""
    entry = (manifest().get("targets") or {}).get(target_key())
    if not isinstance(entry, dict):
        return None
    return installed_binaries(str(entry.get("version") or ""), entry)


def start(db: Session, *, workspace_id: str, created_by: str | None) -> Job:
    """起一次安装。装不了(这个平台没有构建)在起任务之前就说,不留一个注定失败的任务。"""
    chosen = plan()
    if not chosen.available:
        raise MediaToolError(chosen.reason, detail=chosen.detail)
    job = create_job(
        db,
        workspace_id=workspace_id,
        kind="media_tool_install",
        created_by=created_by,
        payload={"tool": "ffmpeg", "target": chosen.target, "version": chosen.version},
        message="jobMsg_mediaToolQueued",
        message_params={"version": chosen.version},
    )
    job_id, target = job.id, chosen.target  # 线程里只捏普通值(见 test_jobs_are_dispatched_by_the_bus)
    dispatch_job(db, job, lambda: _body(job_id, target))
    return job


# --- 跑起来 ---------------------------------------------------------------


def _body(job_id: str, target: str) -> None:
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        if not finish_job(db, job, status="running", progress=0.02):
            return
        entry = (manifest().get("targets") or {}).get(target)
        if not isinstance(entry, dict):
            finish_job(db, job, status="failed", message="jobMsg_mediaToolFailed",
                       **blame(MediaToolError("mediaToolErr_noBuild", detail=target)))
            return
        version = str(entry.get("version") or "")
        say(job, "jobMsg_mediaToolDownloading", params={"version": version})
        emit_job_event(db, job.id, "job.running", {})
    # ↑ 这个短会话退出来就提交了:「正在下载」先落库(任务中心马上看得到),写锁也放掉 ——
    #   几十兆要下一阵,下载期间不攥着任何会话(提交本身归 unit_of_work,领域层不自己 commit)。

    workdir = scratch_dir(SCRATCH)
    try:
        where = _install(job_id, entry, version, workdir)
    except BaseException as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        with unit_of_work() as db:
            job = db.get(Job, job_id)
            if job is not None and not finish_job(db, job, status="running"):
                return  # 被取消了:终态由取消那一侧写
            if job is not None:
                said = exc if isinstance(exc, LocalizedError) else RuntimeError(f"{type(exc).__name__}: {exc}")
                finish_job(db, job, status="failed", message="jobMsg_mediaToolFailed", **blame(said))
        if isinstance(exc, LocalizedError):
            logger.warning("装 ffmpeg(%s)没成:%s", target, exc)
            return
        raise
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    with unit_of_work() as db:
        job = db.get(Job, job_id)
        if job is None or not finish_job(db, job, status="running", progress=0.95):
            return  # 取消:不写配置
        #: 走到这里已经验过「跑得起来、能烧字」,写的就是那一刻验过的那条路径;
        #: 写进配置之后本进程立刻生效并重探(media_tools.save_path 的 after_commit)。
        media_tools.save_path(db, str(where))
        say(job, "jobMsg_mediaToolDone", params={"version": version})
        finish_job(db, job, status="succeeded", progress=1.0,
                   result={"ffmpeg": str(where), "version": version})
        emit_job_event(db, job.id, "job.succeeded", {"ffmpeg": str(where)})
    logger.info("装好了 ffmpeg %s:%s", version, where)


def _install(job_id: str, entry: dict[str, Any], version: str, workdir: Path) -> Path:
    """下下来、解开、验一遍,返回验过的 ffmpeg 路径。**验不过就抛** —— 一个字节都不写进配置。"""
    archives: list[dict[str, Any]] = list(entry.get("archives") or [])
    where = install_dir(version)
    #: 换掉旧的那一份之前先备一份:新的验不过就换回去,不让"装一次更坏了"。
    previous = where.with_name(f".{where.name}.previous")
    staging = workdir / "unpacked"
    staging.mkdir(parents=True, exist_ok=True)

    total = 0
    for index, one in enumerate(archives):
        url = str(one.get("url") or "")
        archive = workdir / f"{index}-{Path(url).name or 'archive'}"
        _download(job_id, url, archive, str(one.get("sha256") or ""), index, len(archives))
        total += archive.stat().st_size
        _unpack(archive, staging)
        if total > MAX_UNPACKED_BYTES:
            raise MediaToolError("mediaToolErr_tooLarge")

    _progress(job_id, 0.85, "jobMsg_mediaToolVerifying")
    ffmpeg, ffprobe = _verify(staging, entry)

    #: 换上去:旧的那份先挪开,新的验过了才删旧的。
    if where.exists():
        shutil.rmtree(previous, ignore_errors=True)
        where.rename(previous)
    try:
        where.parent.mkdir(parents=True, exist_ok=True)
        staging.rename(where)
    except OSError:
        if previous.exists():
            previous.rename(where)
        raise
    shutil.rmtree(previous, ignore_errors=True)
    if not os.access(where / ffmpeg, os.X_OK):  # pragma: no cover — 上面刚验过
        raise MediaToolError("mediaToolErr_notRunnable", path=str(where / ffmpeg))
    return where / ffmpeg


def _download(job_id: str, url: str, target: Path, sha256: str, index: int, count: int) -> None:
    """下一个包:边下边算摘要,下完对上了才留下。进度按字节报(几个包合起来算一条)。"""
    if not secure_url(url):
        raise MediaToolError("mediaToolErr_badUrl", url=url)
    digest = hashlib.sha256()
    written = 0
    try:
        with RetryingClient(timeout=DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                expected = int(response.headers.get("content-length") or 0)
                with target.open("wb") as handle:
                    for chunk in response.iter_bytes(1024 * 256):
                        handle.write(chunk)
                        digest.update(chunk)
                        written += len(chunk)
                        if expected:
                            share = (index + written / expected) / max(1, count)
                            _progress(job_id, 0.05 + 0.75 * share, "jobMsg_mediaToolDownloading")
    except OSError as exc:
        raise MediaToolError("mediaToolErr_downloadFailed", detail=str(exc)) from exc
    if sha256 and digest.hexdigest() != sha256:
        raise MediaToolError("mediaToolErr_digestMismatch", name=target.name)


def _unpack(archive: Path, into: Path) -> None:
    """解一个包。

    归档里那层根目录剥掉(BtbN 的 Windows 包是 `ffmpeg-…/bin/ffmpeg.exe`,而 macOS/Linux 的包
    底下直接就是可执行文件):认「所有成员都在同一个目录前缀下」这一种形状,别的原样解。
    """
    try:
        with zipfile.ZipFile(archive) as bundle:
            names = [one.filename for one in bundle.infolist() if not one.is_dir()]
            prefix = _shared_prefix(names)
            for info in bundle.infolist():
                name = info.filename
                if prefix:
                    if not name.startswith(prefix):
                        continue
                    name = name[len(prefix):]
                if not name or name.endswith("/"):
                    continue
                destination = into / name
                if not str(destination.resolve()).startswith(str(into.resolve())):
                    raise MediaToolError("mediaToolErr_badArchive", name=info.filename)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as source, destination.open("wb") as sink:
                    shutil.copyfileobj(source, sink)
                #: **权限位得自己补**:zipfile 不还原它,而在 macOS / Linux 上少这一位就是"跑不起来"。
                #: Windows 上这一段是空转(那边看的是 .exe 在不在)。
                executable = stat.S_IMODE(info.external_attr >> 16) & 0o111
                if executable or os.name != "nt":
                    destination.chmod(destination.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except zipfile.BadZipFile as exc:
        raise MediaToolError("mediaToolErr_badArchive", name=archive.name) from exc


def _shared_prefix(names: list[str]) -> str:
    """所有成员共有的那一层目录(带结尾斜杠);没有(或只有一个成员)就返回空串。"""
    if len(names) < 2:
        return ""
    first = names[0].split("/")[0] + "/"
    return first if all(one.startswith(first) for one in names) else ""


def _verify(staging: Path, entry: dict[str, Any]) -> tuple[str, str]:
    """装上了没有、装对没有:两个可执行文件都在、ffmpeg 跑得起来、而且**能烧字**。"""
    wanted = {name: str((entry.get("binaries") or {}).get(name) or name) for name in ("ffmpeg", "ffprobe")}
    for label, relative in wanted.items():
        found = staging / relative
        if not found.is_file():
            raise MediaToolError("mediaToolErr_missingBinary", name=label, path=relative)
        if os.name != "nt" and not os.access(found, os.X_OK):
            found.chmod(found.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    ffmpeg = staging / wanted["ffmpeg"]
    if media_tools.version_of(str(ffmpeg)) is None:
        raise MediaToolError("mediaToolErr_notRunnable", path=str(ffmpeg))
    from app.media.render_executor import ffmpeg_has_libass

    ffmpeg_has_libass.cache_clear()
    if not ffmpeg_has_libass(str(ffmpeg)):
        #: 装上了却没有 libass = 带字幕的导出照样被拒。宁可说没装成,也不写进配置让人以为好了。
        raise MediaToolError("mediaToolErr_noLibass", path=str(ffmpeg))
    return wanted["ffmpeg"], wanted["ffprobe"]


def _progress(job_id: str, fraction: float, message: str) -> None:
    """报一次进度(和导出那条路同一个形状:自己的短会话写任务行,不攥着下载期间的长会话)。"""
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        if job is None or not finish_job(db, job, status="running"):
            return
        job.progress = max(float(job.progress or 0.0), round(min(0.94, fraction), 4))
        say(job, message)


__all__ = [
    "InstallPlan",
    "MediaToolError",
    "already_installed",
    "install_dir",
    "installed_binaries",
    "manifest",
    "plan",
    "start",
    "target_key",
]
