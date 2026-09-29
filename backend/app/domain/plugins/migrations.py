"""插件清单的自动迁移:磁盘上的老写法**改成**新写法,而不是让读取代码永远认两种。

和 `core/db.py` 里那串 `_migrate_*` 同一个思路:兼容负担只在升级的那一刻付一次,之后代码里
只剩一种形状。读取路径里的 `if 老写法 elif 新写法` 是会永久留下的税 —— 每加一个字段都要想
"另一种形状下这个字段在哪",而两条分支里总有一条平时没人走、坏了也没人发现。

每个步骤都**幂等**:跑过一次的清单再跑不会变。迁移完写回文件并标 `manifest_version`,
下次扫描直接跳过。

**会改用户磁盘上的文件**。这是有意的:插件目录由这个应用管理,而"你的清单是老格式,请手动
改成这样"是一句没人愿意读的话。原文件先备份成 `<名字>.bak`。
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from mosael_formats.plugin_env import PACKAGE_SOURCE_ENV
from mosael_formats.plugin_manifest import MANIFEST_FILENAME

logger = logging.getLogger(__name__)

#: 清单的规范文件名(清单格式的一部分,见 mosael_formats)。别的名字会在迁移时被改成它 ——
#: 一个目录一份清单,一个名字。
CANONICAL_FILENAME = MANIFEST_FILENAME

#: 迁移时会被认出来并改名的通用写法。
LEGACY_FILENAMES = ("plugin.json",)

#: 当前清单版本。加一个新的迁移步骤就 +1,并把它加进 _STEPS。装好的包存着的清单也跟着升(见
#: db/migrations 的 `upgrade-stored-plugin-manifests`),所以**收紧清单规则时,老清单要能被某一步改合格**。
MANIFEST_VERSION = 2


def _to_runtime_block(raw: dict[str, Any]) -> bool:
    """顶层 kind / entry / mcp → runtime 块。→ 是否改动过。"""
    if isinstance(raw.get("runtime"), dict):
        return False
    mcp = raw.pop("mcp", None)
    runtime: dict[str, Any] = {"kind": raw.pop("kind", None) or "process"}
    entry = raw.pop("entry", None)
    if entry:
        runtime["entry"] = entry
    if isinstance(mcp, dict):
        runtime.update(mcp)
    raw["runtime"] = runtime
    return True


def _to_instance_block(raw: dict[str, Any]) -> bool:
    """顶层 credentials → instance.credentials。

    老写法没有"实例"这个概念,所以凭据挂在包上。搬进 instance 块之后,一个包可以接多次,
    每次各有各的凭据 —— 那正是「TikHub 抖音数据」显示在 bilibili 连接上的那个 bug 的根。
    """
    credentials = raw.pop("credentials", None)
    if not isinstance(credentials, list) or not credentials:
        return False
    instance = raw.setdefault("instance", {})
    if not isinstance(instance, dict):
        instance = {}
        raw["instance"] = instance
    instance.setdefault("credentials", credentials)
    return True


def _to_tools_object(raw: dict[str, Any]) -> bool:
    """数组形态的 tools → 策略对象。

    数组同时承担过三种语义(进程插件的完整声明 / MCP 的白名单 / MCP 的覆盖层),读的人得先
    知道 kind 才能理解那个字段。拆成 declare / recommended / overrides 三个名字,各说各的。

    **expose 定为 "all"**:数组形态此前的行为就是全部暴露,升级不该悄悄把用户在用的工具关掉。
    """
    tools = raw.get("tools")
    if not isinstance(tools, list):
        return False
    entries = [t for t in tools if isinstance(t, dict) and isinstance(t.get("name"), str)]
    overrides = {
        t["name"]: {k: v for k, v in (("read_only", t.get("read_only")), ("node", t.get("node"))) if v}
        for t in entries
        if t.get("read_only") or t.get("node")
    }
    policy: dict[str, Any] = {"expose": "all", "recommended": [t["name"] for t in entries]}
    # 进程插件的声明留在 declare 里;MCP 插件的清单从服务拉,数组里那些只是白名单/覆盖层。
    if str((raw.get("runtime") or {}).get("kind") or "process") != "mcp":
        policy["declare"] = entries
    if overrides:
        policy["overrides"] = overrides
    raw["tools"] = policy
    return True


def _drop_runtime_cache(raw: dict[str, Any]) -> bool:
    """清掉曾经缓存在 manifest 里的运行时数据。

    `_discovered_tools`(MCP 拉回来的清单)现在存在实例上,`_path` 每次扫描现算。它们从来
    不该被写进用户的清单文件 —— 那是我们的状态,不是作者写的东西。
    """
    removed = False
    for key in ("_discovered_tools", "_path"):
        if key in raw:
            raw.pop(key)
            removed = True
    return removed


def _package_mirror_fields_to_sources(raw: dict[str, Any]) -> bool:
    """配置 / 凭据里自带的装包镜像(键是 `PIP_INDEX_URL`、`NPM_CONFIG_REGISTRY` 这类)→ `package_sources`。

    镜像改由宿主按连接注入之后,这些键成了宿主占着的名字,带着它们的清单不再合格 —— 装着 Manim 0.2
    的库,插件页、智能体会话一打开就报「会盖掉宿主给插件的环境变量」。删掉这一格、声明它要的那种源,
    插件读到的还是同一个变量,只是值由宿主给。连接里填过的地址由数据库迁移搬成连接自己的覆盖。
    """
    instance = raw.get("instance")
    if not isinstance(instance, dict):
        return False
    wanted: list[str] = []
    for kind in ("config", "credentials"):
        fields = instance.get(kind)
        if not isinstance(fields, list):
            continue
        kept = []
        for spec in fields:
            key = str(spec.get("key") or "").upper() if isinstance(spec, dict) else ""
            source = next((name for name, keys in PACKAGE_SOURCE_ENV.items() if key in keys), None)
            if source is None:
                kept.append(spec)
            elif source not in wanted:
                wanted.append(source)
        if len(kept) != len(fields):
            instance[kind] = kept
    if not wanted:
        return False
    declared = raw.get("package_sources")
    sources = [str(one) for one in declared] if isinstance(declared, list) else []
    raw["package_sources"] = [*sources, *(one for one in wanted if one not in sources)]
    return True


#: 按顺序跑。加新步骤往后追加,并把 MANIFEST_VERSION +1。
_STEPS = (
    _to_runtime_block,
    _to_instance_block,
    _to_tools_object,
    _drop_runtime_cache,
    _package_mirror_fields_to_sources,
)


def upgrade(raw: dict[str, Any]) -> bool:
    """把一份清单(就地)升到当前版本。→ 是否改动过。磁盘上的清单(`migrate_directory`)和包记录里
    存着的那份(数据库迁移)走的是同一串步骤。"""
    if int(raw.get("manifest_version") or 0) >= MANIFEST_VERSION:
        return False
    for step in _STEPS:
        step(raw)
    raw["manifest_version"] = MANIFEST_VERSION
    return True


def migrate_directory(directory: Path) -> Path | None:
    """把一个插件目录里的清单迁到当前版本,返回规范路径(没有清单则 None)。

    改名 + 改内容都在这里发生,而且都是原地的 —— 扫描之后,磁盘上就只剩新写法。
    """
    path = _find_manifest(directory)
    if path is None:
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return path  # 内容坏了交给 packages 报错,不在这里静默吞掉
    if not isinstance(raw, dict):
        return path

    changed = upgrade(raw)
    canonical = directory / CANONICAL_FILENAME
    if changed:
        _backup(path)
        canonical.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if path != canonical:
            path.unlink()
            logger.info("plugin manifest migrated: %s → %s", path.name, canonical.name)
        else:
            logger.info("plugin manifest migrated: %s", path)
    return canonical if changed else path


def _find_manifest(directory: Path) -> Path | None:
    for name in (CANONICAL_FILENAME, *LEGACY_FILENAMES):
        candidate = directory / name
        if candidate.exists():
            return candidate
    return None


def _backup(path: Path) -> None:
    """迁移前留一份。改的是用户磁盘上的文件,而 JSON 里可能有手写的注释顺序、缩进偏好 ——
    我们只保证语义不丢,不保证字节不变。"""
    backup = path.with_suffix(path.suffix + ".bak")
    if not backup.exists():
        shutil.copy2(path, backup)


__all__ = ["CANONICAL_FILENAME", "LEGACY_FILENAMES", "MANIFEST_VERSION", "migrate_directory", "upgrade"]
