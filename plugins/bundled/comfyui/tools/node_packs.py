"""自定义节点包:列出、搜索、分析(ADR 0042 §7,只读的那一半;安装在第三步)。

    {"op": "node_packs", "content"?}                        → 装了哪些(版本、开没开、来自注册表还是 git 地址、提供哪些节点);
                                                              给了一张图:每种节点来自哪个包,缺的那几种谁能补
    {"op": "node_pack_search", "query"?, "node_types"?}     → 按关键词 / 用途找,或者「这几个节点类型缺了,谁提供」:先查 Manager
                                                              的映射,再查 Comfy 官方注册表;按下载量、星数、最近更新排,标出装了的
    {"op": "node_pack_info", "id", "content"?}              → 装之前看清楚:注册表里这一版的状态(被标记 Flagged、封禁 Banned、弃用)、
                                                              谁发的、许可证、多少人用、最近一次发版;依赖会不会动到 torch;
                                                              和这台机器合不合(系统、加速、ComfyUI 版本);装了的话装的哪一版、
                                                              之后改了什么;能补上图里缺的哪几个

数据从哪来:这台 ComfyUI 的 ComfyUI-Manager(V4:`/v2/customnode/installed`、`/v2/customnode/getmappings`,后者几 MB、一天取一次)、
节点定义里的 `python_module`(一个节点类型来自哪个包的目录,最准),和 **Comfy 官方注册表**(`api.comfy.org`,公开、只读:
`/nodes/search`、`/nodes/<id>`、`/nodes/<id>/versions`)。去注册表走宿主给这个连接的出站(环境变量里的代理),和下载模型同一条路
(sources.fetch);清单里申报 `network:comfy-registry`。
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from typing import Any
from urllib import parse

import canvas
import node_catalog
import sources
from comfy_http import Comfy
from lines import ComfyError, say
from workflow_library import installed_packs, manager_mappings, mapping_short, pack_ids, provides

#: 注册表的地址(测试换成假的)。
REGISTRY = "https://api.comfy.org"
#: 搜索最多回多少个。
MAX_RESULTS = 20
#: 一个包最多列多少个节点类型(KJNodes 两百多个)。
MAX_TYPES = 60
#: 换掉它们就是换掉这台机器的 PyTorch:依赖里有就是高风险。
CORE_TORCH = frozenset({"torch", "torchvision", "torchaudio", "xformers", "triton"})
#: 注册表 id 长什么样(拼进地址里)。
_PACK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$")
#: 版本状态 → 给人看的一句
STATUS_FLAGGED, STATUS_BANNED, STATUS_ACTIVE = "NodeVersionStatusFlagged", "NodeVersionStatusBanned", "NodeVersionStatusActive"


# --- 注册表 --------------------------------------------------------------------------

def _registry(path: str, locale: str) -> Any:
    """问注册表一句;没有(404)→ None。走宿主给的出站(见模块说明)。"""
    try:
        #: 跟着跳转走(注册表对大小写不一样的 id 回 302 指到规范的那个)
        answer = sources.follow(f"{REGISTRY}{path}", method="GET")
    except ComfyError as exc:
        raise ComfyError(say(locale, f"连不上 Comfy 注册表(api.comfy.org):{exc}", f"Can't reach the Comfy Registry (api.comfy.org): {exc}")) from exc
    if answer.status == 404:
        return None
    if answer.status != 200:
        raise ComfyError(say(locale, f"Comfy 注册表回了 HTTP {answer.status}", f"The Comfy Registry answered HTTP {answer.status}"))
    try:
        return json.loads(answer.body.decode("utf-8"))
    except ValueError as exc:
        raise ComfyError(say(locale, "Comfy 注册表回了一段读不懂的东西", "The Comfy Registry answered with something unreadable")) from exc


def _license(raw: Any) -> str:
    """注册表的许可证是一段 JSON 字符串:`{"text": "MIT"}` 或 `{"file": "LICENSE"}`。"""
    if not isinstance(raw, str) or not raw.strip():
        return ""
    try:
        parsed = json.loads(raw)
    except ValueError:
        return raw.strip()[:80]
    if isinstance(parsed, dict):
        return str(parsed.get("text") or (f"见仓库的 {parsed['file']}" if parsed.get("file") else ""))[:80]
    return str(parsed)[:80]


def _publisher(node: dict[str, Any]) -> str:
    publisher = node.get("publisher") if isinstance(node.get("publisher"), dict) else {}
    members = [str(((one or {}).get("user") or {}).get("name") or "") for one in publisher.get("members") or [] if isinstance(one, dict)]
    name = str(publisher.get("name") or "") or next((one for one in members if one), "")
    ident = str(publisher.get("id") or "")
    return f"{name} ({ident})" if name and ident and name != ident else (name or ident)


def _days_since(stamp: Any) -> int | None:
    if not isinstance(stamp, str) or not stamp:
        return None
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - when).days)


def _summary(node: dict[str, Any], installed: dict[str, str]) -> dict[str, Any]:
    """搜索结果里的一个包。"""
    latest = node.get("latest_version") if isinstance(node.get("latest_version"), dict) else {}
    ident = str(node.get("id") or "")
    out: dict[str, Any] = {
        "id": ident,
        "name": str(node.get("name") or ident)[:200],
        "description": str(node.get("description") or "")[:300],
        "publisher": _publisher(node),
        "downloads": int(node.get("downloads") or 0),
        "stars": int(node.get("github_stars") or 0),
        "latest_version": str(latest.get("version") or ""),
        "latest_status": str(latest.get("status") or ""),
        "updated": str(latest.get("createdAt") or "")[:10],
        "license": _license(node.get("license")),
        "repository": str(node.get("repository") or ""),
    }
    if ident.lower() in installed:
        out["installed"] = installed[ident.lower()] or True
    if str(node.get("status") or "") not in ("", "NodeStatusActive"):
        out["pack_status"] = str(node["status"])
    return out


def _rank(entry: dict[str, Any]) -> float:
    days = _days_since(entry.get("updated")) if entry.get("updated") else None
    recency = 6 if days is not None and days <= 30 else 3 if days is not None and days <= 180 else 0
    flagged = -15 if entry.get("latest_status") in (STATUS_FLAGGED, STATUS_BANNED) else 0
    return math.log10(entry["downloads"] + 1) * 10 + math.log10(entry["stars"] + 1) * 5 + recency + flagged + entry.get("_bonus", 0)


# --- 这台 ComfyUI 上 ----------------------------------------------------------------

def _installed_versions(installed: dict[str, dict[str, Any]] | None) -> dict[str, str]:
    """装着的包能叫的名字(小写)→ 装的版本。"""
    out: dict[str, str] = {}
    for key, value in (installed or {}).items():
        version = str(value.get("ver") or "")
        for name in pack_ids({key: value}):
            out[name] = version
    return out


def _mapping_entry(mappings: dict[str, Any] | None, ident: str) -> tuple[str, Any] | None:
    for key, entry in (mappings or {}).items():
        if str(key).lower() == ident.lower() or mapping_short(key) == ident.lower():
            return key, entry
    return None


def _types_of(entry: Any) -> list[str]:
    return [str(one) for one in (entry[0] if isinstance(entry, list) and entry and isinstance(entry[0], list) else [])]


def _graph_types(payload: dict[str, Any], locale: str) -> dict[str, list[str]] | None:
    content = payload.get("content")
    if content is None:
        return None
    if not isinstance(content, dict) or not isinstance(content.get("nodes"), list):
        raise ComfyError(say(locale, "图不是界面格式的工作流", "The graph is not a UI-format workflow"))
    return canvas.refs_by_type(content)


def node_packs(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    installed = installed_packs(comfy)
    mappings = manager_mappings(comfy)
    packs: list[dict[str, Any]] = []
    for key, value in sorted((installed or {}).items(), key=lambda one: one[0].lower()):
        cnr = str(value.get("cnr_id") or "")
        aux = str(value.get("aux_id") or "")
        entry = _mapping_entry(mappings, cnr or key) or (_mapping_entry(mappings, aux.rsplit("/", 1)[-1]) if aux else None)
        types = _types_of(entry[1]) if entry else []
        meta = entry[1][1] if entry and isinstance(entry[1], list) and len(entry[1]) > 1 and isinstance(entry[1][1], dict) else {}
        packs.append({
            "id": cnr or key,
            "folder": key,
            "title": str(meta.get("title_aux") or cnr or key)[:200],
            "version": str(value.get("ver") or ""),
            "enabled": value.get("enabled") is not False,
            "source": "registry" if cnr else "git",
            **({"repository": f"https://github.com/{aux}"} if aux and not cnr else {}),
            "node_types": types[:MAX_TYPES],
            "node_count": len(types),
        })
    out: dict[str, Any] = {"packs": packs, "manager": installed is not None}
    if installed is None:
        out["note"] = str(say(locale, "这台 ComfyUI 没装 ComfyUI-Manager(或者它没答上):列不出装了哪些节点包",
                              "This ComfyUI has no ComfyUI-Manager (or it didn't answer): can't list the installed node packs"))
    graph = _graph_types(payload, locale)
    if graph is not None:
        specs = node_catalog.classes(comfy, graph)
        nodes = []
        for kind, refs in sorted(graph.items()):
            spec = specs.get(kind)
            module = str((spec or {}).get("python_module") or "")
            where = module.split(".", 2)[1] if module.startswith("custom_nodes.") else ("core" if spec else "")
            entry: dict[str, Any] = {"type": kind, "refs": refs[:20], "pack": where or None}
            if spec is None:
                entry["missing"] = True
                entry["offered_by"] = [str(key) for key, value in (mappings or {}).items() if provides(value, kind)][:5]
            nodes.append(entry)
        out["graph_nodes"] = nodes
    return out


def node_pack_search(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    query = str(payload.get("query") or "").strip()
    wanted = payload.get("node_types") or []
    if not isinstance(wanted, list) or not all(isinstance(one, str) for one in wanted) or len(wanted) > 30:
        raise ComfyError(say(locale, "缺的节点类型得是一串名字(最多 30 个)", "The missing node types must be a list of names (at most 30)"))
    if not query and not wanted:
        raise ComfyError(say(locale, "给一个关键词,或者缺的节点类型", "Give a keyword, or the missing node types"))
    installed = _installed_versions(installed_packs(comfy))
    mappings = manager_mappings(comfy) or {}
    by_id: dict[str, dict[str, Any]] = {}
    #: 先查映射:哪个包提供这几个节点类型(最准)
    provided: dict[str, list[str]] = {}
    for kind in wanted:
        for key, entry in mappings.items():
            if provides(entry, kind):
                provided.setdefault(str(key), []).append(kind)
    for key, kinds in provided.items():
        ident = mapping_short(key) if "/" in key else key
        try:
            found = _registry(f"/nodes/{parse.quote(ident, safe='')}", locale) if _PACK_ID.match(ident) else None
        except ComfyError:
            found = None  # 注册表这一下没答上:照映射里的说
        if isinstance(found, dict) and found.get("id"):
            entry = _summary(found, installed)
        else:
            meta = mappings[key][1] if isinstance(mappings[key], list) and len(mappings[key]) > 1 and isinstance(mappings[key][1], dict) else {}
            entry = {"id": key, "name": str(meta.get("title_aux") or key)[:200], "description": "", "publisher": "",
                     "downloads": 0, "stars": 0, "latest_version": "", "latest_status": "", "updated": "", "license": "",
                     "repository": key if key.startswith("http") else "", "registry": False}
            if mapping_short(key) in installed or key.lower() in installed:
                entry["installed"] = installed.get(mapping_short(key)) or installed.get(key.lower()) or True
        entry["provides"] = kinds
        entry["_bonus"] = 50 + 10 * len(kinds)
        by_id[entry["id"]] = entry
    #: 再查注册表:关键词(没给关键词就拿缺的节点类型去搜)
    for text in ([query] if query else wanted[:5]):
        found = _registry(f"/nodes/search?{parse.urlencode({'search': text, 'limit': MAX_RESULTS})}", locale)
        listed = found.get("nodes") if isinstance(found, dict) and isinstance(found.get("nodes"), list) else []
        for node in listed:
            if isinstance(node, dict) and node.get("id") and str(node["id"]) not in by_id:
                by_id[str(node["id"])] = _summary(node, installed)
    ranked = sorted(by_id.values(), key=lambda one: -_rank(one))[:MAX_RESULTS]
    for one in ranked:
        one.pop("_bonus", None)
    return {"packs": ranked, "matched": len(by_id)}


# --- 分析一个 ------------------------------------------------------------------------

def _requirement_name(spec: str) -> str:
    """`torch>=2.4; platform_system == 'Linux'` → `torch`。"""
    return re.split(r"[\s<>=!~;\[(]", spec.strip(), maxsplit=1)[0].lower()


def dependency_risk(dependencies: list[str]) -> tuple[str, list[str]]:
    """依赖动不动 torch:直接要 torch / torchvision / torchaudio / xformers / triton 是高风险(可能把这台机器的 PyTorch 换掉);
    名字里带 torch 的(open-clip-torch、pytorch-lightning)会间接拉 torch,中风险;都没有是低。回(档, 牵动的那几个)。"""
    names = [(spec, _requirement_name(spec)) for spec in dependencies if isinstance(spec, str) and spec.strip()]
    core = [spec for spec, name in names if name in CORE_TORCH]
    if core:
        return "high", core
    near = [spec for spec, name in names if "torch" in name or "xformers" in name or "cuda" in name]
    return ("medium", near) if near else ("low", [])


_OS = {"win32": "windows", "linux": "linux", "darwin": "mac"}


def _os_ok(supported: list[str], platform: str) -> bool | None:
    if not supported or any("independent" in one.lower() for one in supported):
        return True
    mine = _OS.get(platform, "")
    if not mine:
        return None
    keywords = {"windows": ("windows",), "linux": ("linux", "posix"), "mac": ("mac", "darwin", "os x")}[mine]
    return any(any(word in one.lower() for word in keywords) for one in supported)


def _accelerator_ok(supported: list[str], device: str, torch_version: str) -> bool | None:
    if not supported:
        return True
    mine = {"cuda": ("cuda", "nvidia"), "mps": ("metal", "apple", "mps"), "xpu": ("intel",), "cpu": ("cpu",)}.get(device, ())
    if device == "cuda" and "rocm" in torch_version:
        mine = ("rocm", "amd")
    if not mine:
        return None
    return any(any(word in one.lower() for word in mine) for one in supported)


def _comfy_ok(spec: str, current: str) -> bool | None:
    """`>=0.33.0`、`>=0.3,<1.0` 这类写法对这台的版本。说不清就是 None。"""
    if not spec or not current:
        return None if spec else True

    def parts(text: str) -> tuple[int, ...]:
        return tuple(int(one) for one in re.findall(r"\d+", text)[:4])

    have = parts(current)
    for clause in spec.split(","):
        match = re.match(r"\s*(>=|<=|==|>|<|~=)?\s*([\d.]+)", clause)
        if not match:
            return None
        op, version = match.group(1) or "==", parts(match.group(2))
        if not {">=": have >= version, "<=": have <= version, ">": have > version, "<": have < version,
                "==": have[:len(version)] == version, "~=": have[:len(version) - 1] == version[:-1] and have >= version}[op]:
            return False
    return True


def node_pack_info(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    ident = str(payload.get("id") or "").strip()
    if "/" in ident:
        ident = mapping_short(ident)
    if not _PACK_ID.match(ident):
        raise ComfyError(say(locale, f"「{ident}」不是一个节点包的 id", f"“{ident}” is not a node pack id"))
    node = _registry(f"/nodes/{parse.quote(ident, safe='')}", locale)
    if not isinstance(node, dict) or not node.get("id"):
        raise ComfyError(say(locale, f"Comfy 注册表里没有「{ident}」(git 地址装的包不在注册表里,要装请在 Manager 里自己装)",
                             f"The Comfy Registry has no “{ident}” (packs from a git URL aren't in the registry; install those in Manager yourself)"))
    versions = _registry(f"/nodes/{parse.quote(ident, safe='')}/versions", locale)
    versions = [one for one in versions if isinstance(one, dict)] if isinstance(versions, list) else []
    newest = versions[0] if versions else (node.get("latest_version") or {})
    usable = next((one for one in versions if one.get("status") == STATUS_ACTIVE and not one.get("deprecated")), None)
    candidate = usable or (node.get("latest_version") if isinstance(node.get("latest_version"), dict) else {}) or {}
    try:
        stats = comfy.system_stats()
    except ComfyError:
        stats = {}
    system = stats.get("system") if isinstance(stats.get("system"), dict) else {}
    devices = stats.get("devices") if isinstance(stats.get("devices"), list) else []
    device = str((devices[0] or {}).get("type") or "") if devices and isinstance(devices[0], dict) else ""
    current = str(system.get("comfyui_version") or "")
    torch_version = str(system.get("pytorch_version") or "")
    platform = str(system.get("os") or "")

    dependencies = [str(one) for one in candidate.get("dependencies") or [] if isinstance(one, str)]
    risk, touching = dependency_risk(dependencies)
    supported_os = [str(one) for one in candidate.get("supported_os") or node.get("supported_os") or [] if isinstance(one, str)]
    accelerators = [str(one) for one in candidate.get("supported_accelerators") or node.get("supported_accelerators") or []
                    if isinstance(one, str)]
    comfy_spec = str(candidate.get("supported_comfyui_version") or node.get("supported_comfyui_version") or "")

    installed = installed_packs(comfy)
    mine = next((value for key, value in (installed or {}).items()
                 if ident.lower() in pack_ids({key: value})), None)
    installed_version = str(mine.get("ver") or "") if mine else ""
    newer = []
    if installed_version:
        for one in versions:
            if str(one.get("version") or "") == installed_version:
                break
            newer.append(one)

    mappings = manager_mappings(comfy)
    entry = _mapping_entry(mappings, ident)
    types = _types_of(entry[1]) if entry else []
    out: dict[str, Any] = {
        **_summary(node, _installed_versions(installed)),
        "newest_version": {
            "version": str(newest.get("version") or ""), "status": str(newest.get("status") or ""),
            "deprecated": bool(newest.get("deprecated")), "date": str(newest.get("createdAt") or "")[:10],
        },
        "flagged_versions": sum(1 for one in versions if one.get("status") == STATUS_FLAGGED),
        "banned_versions": sum(1 for one in versions if one.get("status") == STATUS_BANNED),
        "install_version": str(candidate.get("version") or ""),
        "dependencies": dependencies[:40],
        "dependency_risk": risk,
        "torch_touching": touching,
        "compatibility": {
            "os": {"supported": supported_os, "this_machine": platform, "ok": _os_ok(supported_os, platform)},
            "accelerator": {"supported": accelerators, "this_machine": device, "ok": _accelerator_ok(accelerators, device, torch_version)},
            "comfyui": {"required": comfy_spec, "this_machine": current, "ok": _comfy_ok(comfy_spec, current)},
        },
        "node_types": types[:MAX_TYPES],
        "node_count": len(types),
    }
    if installed_version:
        out["installed"] = {"version": installed_version, "enabled": mine.get("enabled") is not False if mine else True,
                            "newer_versions": [str(one.get("version") or "") for one in newer][:20],
                            "changelog": [{"version": str(one.get("version") or ""), "text": str(one.get("changelog") or "")[:600]}
                                          for one in newer if one.get("changelog")][:10]}
    graph = _graph_types(payload, locale)
    if graph is not None:
        specs = node_catalog.classes(comfy, graph)
        missing = [kind for kind in graph if kind not in specs]
        out["fills_missing"] = [kind for kind in missing if entry and provides(entry[1], kind)]
        out["graph_missing"] = missing
    out["advice"] = _advice(out, locale)
    return out


def _advice(info: dict[str, Any], locale: str) -> list[str]:
    """几句要点(装之前该知道的),给智能体照着说。"""
    lines: list[str] = []
    newest = info["newest_version"]
    if newest["status"] == STATUS_BANNED:
        lines.append(str(say(locale, f"最新的 {newest['version']} 被注册表封禁(Banned):不要装", f"The newest version {newest['version']} is Banned: don't install it")))
    elif newest["status"] == STATUS_FLAGGED:
        lines.append(str(say(locale, f"最新的 {newest['version']} 被注册表标记(Flagged),没通过审核:不装这一版"
                             + (f";最近一个正常的版本是 {info['install_version']}" if info["install_version"] else ""),
                             f"The newest version {newest['version']} is Flagged (failed review): don't install it"
                             + (f"; the latest normal version is {info['install_version']}" if info["install_version"] else ""))))
    if newest["deprecated"]:
        lines.append(str(say(locale, "这一版标了弃用", "This version is deprecated")))
    if info.get("pack_status"):
        lines.append(str(say(locale, f"这个包在注册表里的状态是 {info['pack_status']}", f"The pack's registry status is {info['pack_status']}")))
    if info["dependency_risk"] == "high":
        lines.append(str(say(locale, f"依赖里直接有 {'、'.join(info['torch_touching'])}:装的时候可能把这台机器的 PyTorch 换掉,高风险",
                             f"Depends directly on {', '.join(info['torch_touching'])}: installing may replace this machine's PyTorch (high risk)")))
    elif info["dependency_risk"] == "medium":
        lines.append(str(say(locale, f"依赖 {'、'.join(info['torch_touching'])} 可能间接拉 torch,装之前留意",
                             f"{', '.join(info['torch_touching'])} may pull torch indirectly; be careful")))
    for key, label_zh, label_en in (("os", "系统", "OS"), ("accelerator", "加速", "accelerator"), ("comfyui", "ComfyUI 版本", "ComfyUI version")):
        check = info["compatibility"][key]
        if check["ok"] is False:
            lines.append(str(say(locale, f"{label_zh}不合:它要 {check['supported'] if key != 'comfyui' else check['required']},"
                                 f"这台是 {check['this_machine']}",
                                 f"{label_en} mismatch: it needs {check['supported'] if key != 'comfyui' else check['required']}, "
                                 f"this machine has {check['this_machine']}")))
    return lines


__all__ = ["REGISTRY", "dependency_risk", "node_pack_info", "node_pack_search", "node_packs"]
