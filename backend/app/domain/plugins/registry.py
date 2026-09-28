"""插件市场:一份可浏览的索引,以及「从一个地址装下来」。

此前装插件的唯一办法是**手动把文件夹丢进插件目录再点扫描**。这对写插件的人没问题,
对用它的人是道墙 —— 而插件的价值恰恰在于用的人比写的人多得多。

## 索引就是一份 JSON

    {"plugins": [{"id": "...", "name": "...", "description": "...",
                  "version": "...", "author": "...", "homepage": "...",
                  "download": "https://.../x.zip", "permissions": ["network:x"]}]}

**地址可配置**,默认指向本项目的那一份。格式是普通 JSON、没有签名也没有账号 ——
谁都能自己架一个,包括公司内网。这是有意的:插件系统的价值在于长出来的东西,
而一个必须经过我们审核的市场长不出多少东西。

代价是**索引不是信任背书**。所以真正的防线不在这里,而在装的那一刻:装什么、它声明了
哪些权限,都摊开给用户看过才动手(见 install_archive 与前端的安装确认)。

## 装的时候在防什么

装插件 = 在用户机器上放一份**会被执行**的代码。包本身的检查 —— 压缩包里的路径穿越
(`../../.ssh/authorized_keys`)、符号链接、解压炸弹、没有清单或清单不合法的垃圾包 —— 在
`mosael_formats.plugin_archive`,社区服务上架时过的是同一份(ADR 0026)。这里再挡的是桌面端自己的事:
悄悄覆盖掉一个已经装好并且已经填了凭据的包、拿市场上的包顶替随应用发的插件。挡不住的是「这个作者是
不是好人」—— 那件事只能由用户看着权限清单自己决定,所以那份清单必须在装之前就看得见。
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.orm import Session
from mosael_formats import plugin_archive

from app.core.http_retry import RetryingClient
from app.domain import deployment
from app.domain.effects import plugin_tool_effects
from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.manifest import Manifest

logger = logging.getLogger(__name__)

#: 压缩包最大多少、解压后最大多少(上限的由来见 mosael_formats.plugin_archive)。留成本模块的名字,
#: 装的那一刻按**此刻**的值传进去。
MAX_ARCHIVE_BYTES = plugin_archive.MAX_ARCHIVE_BYTES
MAX_UNPACKED_BYTES = plugin_archive.MAX_UNPACKED_BYTES

DOWNLOAD_TIMEOUT_SECONDS = 60.0
REGISTRY_TIMEOUT_SECONDS = 15.0

#: 内置的市场索引:**最新一次正式发版附带的那一份**,和插件包是同一次发版、从同一份源码产出的
#: (见 scripts/sync-plugin-registry.py --release 与 docs/RELEASING.md)。
#:
#: 不再读官网上那份(website/public/plugins/registry.json):那份由 main 生成,版本号是 main 上的,
#: 而插件包只在打 tag 时产出 —— main 上改了版本、还没发版的那段时间里,它许的新版下载地址给不出来,
#: 「更新」装回旧版,「有新版」永远不消失。
#:
#: `releases/latest/download/…` 由 GitHub 302 到附件的 CDN 地址(fetch_index 跟随跳转、单次超时、
#: 不重试);索引里每条的下载地址钉在**生成它的那个 tag** 上,所以读索引的那一刻恰好发了新版也不会
#: 拿到「新索引 + 旧包」。部署管理员可以换成自己那一份(见 index_url)。
DEFAULT_REGISTRY_URL = "https://github.com/Alndaly/Mosael/releases/latest/download/registry.json"


def index_url(db: Session) -> str:
    """这台部署读哪一份索引:部署管理员配过的那份,没配就是内置的那份。"""
    return deployment.plugin_registry_url(db) or DEFAULT_REGISTRY_URL


def fetch_index(url: str) -> list[dict[str, Any]]:
    """拉一份索引。拉不到就是拉不到 —— 不缓存、不兜底到一份内置清单。

    兜底会让「市场里怎么少了一个」变成一个查不清的问题:用户看到的到底是这一刻的索引,
    还是某次成功之后留下的旧副本?

    拉不到时市场里照样列着随应用内置的插件(见 routes/plugins.browse_market)—— 那不是远端的
    兜底副本,而是本机装着的事实;拉不到的原因照样交给界面说出来。
    """
    if not url.startswith(("http://", "https://")):
        raise PluginDomainError("pluginErr_marketBadScheme")
    try:
        # 市场列表是一段前台交互,不能继承 AI 供应商那套多次退避重试。远端挂掉时应在一次
        # 明确的超时后把错误交给界面,否则 15 秒会被放大数倍,用户只会一直看到骨架屏。
        with RetryingClient(
            timeout=REGISTRY_TIMEOUT_SECONDS,
            follow_redirects=True,
            max_retries=0,
        ) as client:
            response = client.get(url)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        # 连上了、对方说「没有」:说清是**哪个地址**(跟过跳转之后的那个 —— 默认索引会跳到某一版的
        # 附件上,是哪一版正是要知道的)回了几。httpx 的原文整句带着一个 MDN 链接,不是给人看的。
        raise PluginDomainError(
            "pluginErr_marketStatus", url=str(exc.response.url), status=exc.response.status_code
        ) from exc
    except httpx.HTTPError as exc:
        raise PluginDomainError("pluginErr_marketUnreachable", detail=str(exc)) from exc
    except ValueError as exc:
        raise PluginDomainError("pluginErr_marketNotJson") from exc
    entries = payload.get("plugins") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        raise PluginDomainError("pluginErr_marketBadShape", example='{"plugins": [...]}')
    return [entry for entry in entries if isinstance(entry, dict) and entry.get("id")]


def _market_effects(manifest: Manifest, tool: dict[str, Any]) -> str:
    """市场里一个声明过的工具的后果。和装上之后(plugins.tools.all_tools)同一个算法 —— 覆盖 > 声明 > 包缺省。"""
    override = manifest.overrides.get(str(tool["name"]))
    return plugin_tool_effects(
        read_only=bool((override and override.read_only) or tool.get("read_only") is True),
        declared=(override.effects if override and override.effects else None) or tool.get("effects"),
        default=manifest.default_effects or None,
    )


def bundled_entry(manifest: Manifest) -> dict[str, Any]:
    """随应用内置的插件在市场里的那一条,**由本机那份清单生成**,形状与远端索引的条目一样。

    和 scripts/sync-plugin-registry.py 给内置插件生成的条目一一对应:`bundled` 为真、没有下载
    地址(它跟着应用走,不从市场装)。取本机清单而不是远端那条,是因为远端可能更旧、可能拉不到,
    而这台机器上装着的是哪一版只有本机知道。
    """
    return {
        "id": manifest.id,
        "name": manifest.name,
        "version": manifest.version,
        "description": (manifest.skills[0].get("description") if manifest.skills else "") or "",
        "author": manifest.author.name,
        "author_url": manifest.author.url,
        "docs": manifest.docs,
        # 主页只从清单来(仓库里每个插件都写了),和生成索引的脚本同一条规矩。
        "homepage": manifest.homepage,
        "download": "",
        "permissions": list(manifest.permissions),
        "runtime": manifest.runtime.kind,
        "provides": list(manifest.provides),
        "tools": [
            {
                "name": str(tool["name"]),
                "label": tool.get("label") or "",
                "description": tool.get("description") or "",
                # 和 scripts/sync-plugin-registry.py 同一个算法(domain/effects):装之前就看得到哪些工具会先问你。
                "effects": _market_effects(manifest, tool),
            }
            for tool in manifest.declared_tools
        ],
        "bundled": True,
    }


def _download(url: str) -> bytes:
    if not url.startswith(("http://", "https://")):
        raise PluginDomainError("pluginErr_downloadBadScheme")
    written = bytearray()
    try:
        with RetryingClient(timeout=DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    written.extend(chunk)
                    if len(written) > MAX_ARCHIVE_BYTES:
                        raise PluginDomainError("pluginErr_archiveTooLarge")
    except httpx.HTTPError as exc:
        raise PluginDomainError("pluginErr_downloadFailed", detail=str(exc)) from exc
    return bytes(written)


def inspect_archive(data: bytes) -> tuple[dict[str, Any], Path, Path]:
    """看清楚这个包、再解到临时目录。返回 (清单, 清单所在目录, 临时根目录)。

    **先看清楚再落地**:成员安全、清单存在且合法都在内存里查完(`read_plugin_archive`),不合格的包
    不在磁盘上留下任何东西;解压时 `safe_extract` 逐条再查一次。调用方负责删掉临时根目录。
    """
    try:
        package = plugin_archive.read_plugin_archive(
            data, max_archive_bytes=None, max_unpacked_bytes=MAX_UNPACKED_BYTES
        )
    except plugin_archive.ArchiveError as exc:
        raise PluginDomainError.relay(exc) from exc
    workdir = Path(tempfile.mkdtemp(prefix="mosael-plugin-install-"))
    try:
        with plugin_archive.open_archive(data, max_archive_bytes=None) as archive:
            plugin_archive.safe_extract(archive, workdir, max_unpacked_bytes=MAX_UNPACKED_BYTES)
    except plugin_archive.ArchiveError as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        raise PluginDomainError.relay(exc) from exc
    except BaseException:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    return package.raw, workdir.joinpath(*package.root.split("/")) if package.root else workdir, workdir


#: 同一时刻只换一个插件目录。两次安装同一个 id 撞在一起时,先到的装完、后到的按「已经装过」处理,
#: 而不是两边都判「还没装」、一个把目录挪进另一个里面去。
_INSTALL_LOCK = threading.Lock()


def install_archive(data: bytes, plugins_dir: Path, *, overwrite: bool = False) -> dict[str, Any]:
    """把一个 zip 装进插件目录。返回它的清单。

    `overwrite=False` 时**不覆盖已装的同 id 包**。覆盖是一件要单独同意的事:那个目录里
    可能已经有用户填过的东西,而且新版本可能声明了完全不同的权限。

    **随应用发的插件不能被市场上的包顶替**(见 bundled):它们和插件目录里别的包住在一起,此前一个
    id 写成 `dev.mosael.comfyui` 的第三方包选「更新」就能把随包的 ComfyUI 整个换成自己的代码。

    **换目录是原子的**:先把新版本完整地放到插件目录里一个隐藏的暂存目录(同一个文件系统),再用两次
    rename 换上去。此前是先 rmtree 旧目录再从临时目录 move 过来 —— 临时目录和插件目录不在同一个
    文件系统时 move 是逐个文件拷贝,拷到一半失败,留下的是半个新版本、旧版本已经没了。
    """
    from app.domain.plugins import bundled

    raw, root, workdir = inspect_archive(data)
    staging: Path | None = None
    try:
        plugin_id = str(raw["id"]).strip()  # 形状在 parse 里查过(manifest.PLUGIN_ID_RE)
        name = raw.get("name") or plugin_id
        if bundled.is_bundled(plugin_id):
            raise PluginDomainError("pluginErr_bundledCannotReplace", name=name)
        target = plugins_dir / plugin_id
        if target.exists() and not overwrite:
            raise PluginDomainError("pluginErr_alreadyInstalled", name=name)
        plugins_dir.mkdir(parents=True, exist_ok=True)
        staging = plugins_dir / f".{plugin_id}.installing-{uuid.uuid4().hex[:8]}"
        shutil.move(str(root), str(staging))
        with _INSTALL_LOCK:
            _swap_in(staging, target, overwrite=overwrite, name=name)
        staging = None
        logger.info("装上插件 %s(%s)", plugin_id, raw.get("version"))
        return raw
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)


def _swap_in(staging: Path, target: Path, *, overwrite: bool, name: str) -> None:
    """把暂存目录换成 `target`。换失败时旧版本原样留着。"""
    if not target.exists():
        staging.rename(target)
        return
    if not overwrite:
        raise PluginDomainError("pluginErr_alreadyInstalled", name=name)
    retired = target.with_name(f".{target.name}.replaced-{uuid.uuid4().hex[:8]}")
    target.rename(retired)
    try:
        staging.rename(target)
    except OSError:
        retired.rename(target)
        raise
    shutil.rmtree(retired, ignore_errors=True)


def download_archive(url: str) -> bytes:
    """把一个插件包下下来(大小有上限,只认 http/https)。装和预览都从这里拿字节。"""
    return _download(url)


def read_manifest(data: bytes) -> dict[str, Any]:
    """只看不装:解到临时目录读一遍清单就扔。

    给「装之前先让用户看看它要什么权限」用 —— 权限清单写在清单里,而清单在包里面,不下下来看不到;
    也给「从市场更新」先认一眼包里**实际**是哪一版(见 domain/plugins/updates)。
    """
    raw, _, workdir = inspect_archive(data)
    shutil.rmtree(workdir, ignore_errors=True)
    return raw




__all__ = [
    "MAX_ARCHIVE_BYTES",
    "MAX_UNPACKED_BYTES",
    "bundled_entry",
    "download_archive",
    "fetch_index",
    "inspect_archive",
    "install_archive",
    "read_manifest",
]
