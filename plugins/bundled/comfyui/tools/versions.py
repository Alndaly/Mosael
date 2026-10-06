"""让 Mosael 装的那一份换版本(ADR 0041 §4「更新、回滚」)。宿主经 `comfyui_generation` 按 op 问:

    {"op": "service_versions", "directory"}
        → 装着哪个、能更新到哪个、能回到哪个、有没有被打断没做完的
    {"op": "service_update", "directory", "version", "sources", "log", "pip_cache"}
        → 流式(和 service_install 同一种一步一行):换到一个更新的钉死版本;没成就自己换回去
    {"op": "service_rollback", "directory", "sources", "log", "pip_cache"}
        → 流式:回到上一版(也收拾被打断的更新 / 回退)

**换版本只换源码,venv 不重建**:新源码解到旁边(`ComfyUI.next`);装新依赖之前 `pip freeze` 存一份(`pip-freeze-<旧版本>.txt`);
旧源码改名 `ComfyUI.previous`、新源码换上来,`models`、`custom_nodes`、`user`(工作流、设置)、`input`、`output` 五样从旧的搬进
新的(新包自带的占位目录、示例文件里旧的没有的补进去);再按新的 requirements 装依赖。中间失败或取消,**自己换回去**:五样搬回、
旧源码换回、按那份 freeze 把变了版本的包装回(`--no-deps`,只装变了的)。宿主接着试起一次;没通过,它调 `service_rollback`。

**上一版留一步**:更新成了以后 `ComfyUI.previous` 和那份 freeze 留着,「回到上一版」用它们(不重下);下一次更新时换掉。回到上一版
之后新的那份删掉(要再更新就重下,12 MB)。PyTorch 三件不在 freeze 的对比里:换版本不动它们(装依赖不加 --upgrade,装完核对过)。

**被强行打断**(后端被杀、断电):记录里留着标记 —— `updating` 换到一半、`restoring` 源码换回来了、依赖还没装回去。
`service_versions` 说出来,`service_launch` 不起它(半新半旧的环境起来也是错的),安装也不在它上面接着装;连接页上「换回 x」
就是 `service_rollback`,从停下的地方收拾干净。删东西只删这几个换下来的源码目录,不跟着符号链接出去。
"""

from __future__ import annotations

import platform
import re
import shutil
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import managed
import pinned
import service
from lines import ComfyError, say

Emit = Callable[[dict[str, Any]], None]

#: 换版本时用到的几个目录(都在安装目录里,和 `ComfyUI/` 并排)。
NEXT = f"{managed.SOURCE}.next"
PREVIOUS = managed.PREVIOUS
DISCARDED = f"{managed.SOURCE}.discarded"
SKELETON = f"{managed.SOURCE}.skeleton"
#: 跟着「在用的那一份源码」走的五样:模型、自定义节点(pysssss、Manager 装的)、工作流和设置、输入、输出。
CARRIED = ("models", "custom_nodes", "user", "input", "output")
UPDATE_STEPS = ("disk", "download", "extract", "freeze", "switch", "requirements", "nodes")
ROLLBACK_STEPS = ("switch", "restore", "cleanup")
#: 更新要的空间:新源码近 50 MB,换下来的包(前端包一个就几十 MB)和 pip 的临时文件,宽松地按 1 GB。
UPDATE_NEED = 1 * managed.GB
#: 不进 freeze 对比的:PyTorch 三件(换版本不动它们;CUDA 版带 +cu130 这类后缀,装回去要走 PyTorch 源)。
TORCH_NAMES = frozenset(name for name, _version in managed.TORCH)
_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*(\S+)$")


def _not_installed(locale: str) -> ComfyError:
    return ComfyError(say(locale, "这一份还没装好:装好了才能换版本", "This copy isn't fully installed; finish installing first"))


def _nothing_to_go_back_to(locale: str) -> ComfyError:
    return ComfyError(say(locale, "没有可以回去的上一版(更新之后才有;回到上一版之后就没了)",
                          "There's no earlier version to go back to (there is one after an update, until you go back)"))


def _numbers(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version))


def newer(version: str, than: str) -> bool:
    return _numbers(version) > _numbers(than)


def _remove_tree(path: Path) -> None:
    """删掉一个换下来的目录。它本身是符号链接就只删链接;里面的链接 rmtree 也只删链接,不跟着出去。"""
    if path.is_symlink():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _installed(root: Path, record: dict[str, Any], locale: str) -> str:
    """装好了的话是哪个版本;没装好抛(更新只在装好的那一份上做)。"""
    done = managed.done_steps(root, record, python_minor=str(record.get("python_minor") or ""),
                              flavour=str(record.get("flavour") or ""), windows=sys.platform == "win32")
    if not set(managed.STEPS) - {"disk"} <= done or not record.get("comfyui"):
        raise _not_installed(locale)
    return str(record["comfyui"])


def _back_to(root: Path, record: dict[str, Any]) -> str:
    """「回到上一版」回到哪个版本:依赖还没装回去的那一次、或者留着的上一版;都没有是空串。"""
    restoring = record.get("restoring") or {}
    if restoring.get("version"):
        return str(restoring["version"])
    previous = record.get("previous") or {}
    if previous.get("version") and (record.get("updating") or (root / PREVIOUS / "main.py").is_file()):
        return str(previous["version"])
    return ""


# --- service_versions -----------------------------------------------------------


def versions(payload: dict[str, Any], locale: str) -> dict[str, Any]:
    """装着哪个、钉死的最新是哪个、能更新到哪个(没有更新的是空串)、能回到哪个、有没有被打断没做完的(`update` / `rollback`)。只看、不写。"""
    root = managed._root(payload, locale)
    record = managed.read_record(root)
    current = str(record.get("comfyui") or "")
    unfinished = "update" if record.get("updating") else "rollback" if record.get("restoring") else ""
    newer_ones = [one for one in managed.COMFYUI_PINNED if current and newer(one, current)]
    return {
        "current": current,
        "latest": managed.COMFYUI_VERSION,
        "update": newer_ones[-1] if newer_ones and not unfinished else "",
        "previous": _back_to(root, record),
        "unfinished": unfinished,
    }


def launch(payload: dict[str, Any], locale: str) -> dict[str, Any]:
    """`service_launch`,先看一眼:让 Mosael 装的那一份上一次换版本没做完(半新半旧)就不起它,说去「换回」。"""
    raw = str(payload.get("directory") or "").strip()
    problem = managed.unfinished_change(managed.read_record(Path(raw).expanduser()), locale) if raw else ""
    if problem:
        raise ComfyError(problem)
    return service.launch(payload, locale)


# --- 共用的几步 -------------------------------------------------------------------


def _job(payload: dict[str, Any], locale: str, emit: Emit, record: dict[str, Any], *, titles: dict[str, dict[str, str]],
         steps: tuple[str, ...], version: str, is_cancelled: Callable[[], bool], log: managed._Log,
         retry: tuple[str, str]) -> managed._Job:
    """换版本用的那一份活:venv 是装好的那个(不重建、不问显卡),PyTorch 的种类、Python 小版本按安装记录。`retry` 是失败了
    点哪个按钮再来(pip 失败的那一句里说)。"""
    root = managed._root(payload, locale)
    machine = managed.Machine(system=sys.platform, arch=platform.machine(), python_minor=str(record.get("python_minor") or ""))
    return managed._Job(root=root, base=managed.venv_python(root, windows=machine.system == "win32"), machine=machine,
                        flavour=str(record.get("flavour") or ""), sources=managed._sources(payload),
                        pip_cache=str(payload.get("pip_cache") or ""), locale=locale, log=log,
                        report=managed._Reporter(emit, titles, steps), is_cancelled=is_cancelled, record=record,
                        version=version, titles=titles, retry=retry)


def _freeze(job: managed._Job) -> str:
    said: list[str] = []
    code, tail = managed._stream(job, [str(job.python), "-m", "pip", "freeze", "--disable-pip-version-check"],
                                 timeout=managed.SHORT_TIMEOUT_SECONDS, on_line=said.append)
    if code != 0:
        detail = (tail[-1] if tail else f"exit {code}")[:300]
        raise ComfyError(job.say(f"记下装着的包(pip freeze)失败:{detail}", f"Recording the installed packages (pip freeze) failed: {detail}"))
    return "\n".join(said) + "\n"


def _pins(text: str) -> dict[str, tuple[str, str]]:
    """freeze 的输出 → {规范化的包名: (包名, 版本)}。`-e`、`@ 地址`、注释不是 PyPI 上的某个版本,不收;PyTorch 三件不收。"""
    pins: dict[str, tuple[str, str]] = {}
    for line in text.splitlines():
        found = _PIN.match(line.strip())
        if not found:
            continue
        key = re.sub(r"[-_.]+", "-", found.group(1)).lower()
        if key not in TORCH_NAMES:
            pins[key] = (found.group(1), found.group(2))
    return pins


def _restore(job: managed._Job, freeze_name: str, title: dict[str, str]) -> None:
    """按换版本前记下的那份,把版本变了(或没了)的包装回那个版本(`--no-deps`:装回的是一整套原样,不再解依赖)。都没变就不调 pip。"""
    path = job.root / freeze_name
    try:
        saved = _pins(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ComfyError(job.say(f"换版本前记下的包清单不见了:{path}", f"The package list recorded before the change is missing: {path}")) from exc
    now = _pins(_freeze(job))
    changed = [f"{name}=={version}" for key, (name, version) in sorted(saved.items()) if now.get(key, ("", ""))[1] != version]
    job.log.line(f"和换版本前不一样的包:{len(changed)} 个" + (f"({', '.join(changed)})" if changed else ""))
    if changed:
        managed._pip_install(job, ["--no-deps", *changed], index=job.sources["pip_index_url"], torch_step=False, title=title)


def _carry(job: managed._Job, origin: Path, destination: Path, *, fresh: bool) -> None:
    """五样从 `origin` 搬进 `destination`(同一块盘上改名,不拷)。

    `fresh`:`destination` 是刚解开的新源码,它自带的同名目录是占位的 —— 先挪到一边,旧的搬过去之后把旧的里没有的那几项补进去
    (新版本多出来的模型目录、示例节点),剩下的连同那一边删掉。不是 `fresh`(换回去):`destination` 里已经有的不动(那说明这一样
    还没搬过来过),只搬它没有的。"""
    skeleton = job.root / SKELETON
    for name in CARRIED:
        moving = origin / name
        if not _present(moving):
            continue
        target = destination / name
        if _present(target):
            if not fresh:
                job.log.line(f"{target} 已经在了,{moving} 留在原处")
                continue
            skeleton.mkdir(exist_ok=True)
            target.replace(skeleton / name)
        moving.replace(target)
        job.log.line(f"搬 {moving} → {target}")
        placeholder = skeleton / name
        if fresh and placeholder.is_dir() and target.is_dir() and not target.is_symlink():
            for entry in placeholder.iterdir():
                if not _present(target / entry.name):
                    entry.replace(target / entry.name)
    _remove_tree(skeleton)


def _switch(job: managed._Job, current: str, target: str, freeze_name: str) -> None:
    """换上新源码:上上一版(上一次更新留下的)这时才删 —— 先从记录里去掉再删,删到一半断了也不会被当成能回去的那一版;
    再在记录里写下「换到一半」和上一版,改名、搬五样,最后记新版本。写下「换到一半」之后哪一下失败(Windows 上文件被占着改不了名)
    都抛,调用方见到这个标记就换回去;之前失败的,原来那份没动。"""
    root, record = job.root, job.record
    old = record.pop("previous", None)
    if old is not None:
        managed._write_record(root, record)
        _remove_tree(root / PREVIOUS)
        if old.get("freeze") and old["freeze"] != freeze_name:
            (root / str(old["freeze"])).unlink(missing_ok=True)
    _remove_tree(root / SKELETON)
    record["previous"] = {"version": current, "freeze": freeze_name}
    record["updating"] = target
    managed._write_record(root, record)
    (root / managed.SOURCE).replace(root / PREVIOUS)
    (root / NEXT).replace(root / managed.SOURCE)
    _carry(job, root / PREVIOUS, root / managed.SOURCE, fresh=True)
    record["comfyui"] = target
    managed._write_record(root, record)


def _go_back(job: managed._Job, titles: dict[str, dict[str, str]], announce: Callable[[str], None]) -> str:
    """换回上一版,从停下的地方接着:源码还没换回来就换(五样搬回去、新的那份挪开),依赖还没装回去就装,最后删掉换下来的。
    每一步做完记一笔,中途再被打断下次接着来。交回换回到的版本。`announce(key)` 在每一步开始时说一声。"""
    root, record = job.root, job.record
    previous = record.get("previous") or {}
    if previous.get("version") and (root / PREVIOUS / "main.py").is_file():
        announce("switch")
        if _present(root / managed.SOURCE):
            _carry(job, root / managed.SOURCE, root / PREVIOUS, fresh=False)
            _remove_tree(root / DISCARDED)
            (root / managed.SOURCE).replace(root / DISCARDED)
        (root / PREVIOUS).replace(root / managed.SOURCE)
        record["comfyui"] = str(previous["version"])
        record["restoring"] = previous
        record.pop("previous", None)
        record.pop("updating", None)
        managed._write_record(root, record)
    restoring = record.get("restoring") or {}
    if restoring.get("freeze"):
        announce("restore")
        _restore(job, str(restoring["freeze"]), titles["restore"])
        (root / str(restoring["freeze"])).unlink(missing_ok=True)
        record.pop("restoring", None)
        managed._write_record(root, record)
    announce("cleanup")
    for name in (DISCARDED, NEXT, SKELETON):
        _remove_tree(root / name)
    if record.pop("updating", None) is not None:
        # 换到一半就断了、还没来得及改名:源码一直是原来那份,依赖也还没动;记的「上一版」那份已经删了,不再提它
        stale = record.pop("previous", None) or {}
        if stale.get("freeze"):
            (root / str(stale["freeze"])).unlink(missing_ok=True)
    managed._write_record(root, record)
    return str(record.get("comfyui") or "")


def _update_titles(current: str, target: str) -> dict[str, dict[str, str]]:
    return {
        "disk": {"zh": "查剩余空间", "en": "Check free disk space"},
        "download": {"zh": f"下载 ComfyUI {target} 源码(按 sha256 校验)", "en": f"Download the ComfyUI {target} source (checked by sha256)"},
        "extract": {"zh": f"解到 {current} 旁边", "en": f"Unpack it next to {current}"},
        "freeze": {"zh": f"记下现在装着的包(pip freeze,换回 {current} 时用)",
                   "en": f"Record the installed packages (pip freeze, used to go back to {current})"},
        "switch": {"zh": "换上新源码,模型、自定义节点、工作流和设置、输入输出搬过去",
                   "en": "Switch to the new source and move models, custom nodes, workflows and settings, inputs and outputs over"},
        "requirements": {"zh": "装新版本的依赖和 ComfyUI-Manager", "en": "Install the new version's dependencies and ComfyUI-Manager"},
        "nodes": {"zh": "确认 pysssss 还在(模型库要它)", "en": "Make sure pysssss is still there (the model library needs it)"},
    }


def _rollback_titles(back_to: str) -> dict[str, dict[str, str]]:
    return {
        "switch": {"zh": f"换回 ComfyUI {back_to} 的源码,模型这些搬回去", "en": f"Switch back to the ComfyUI {back_to} source and move models and the rest back"},
        "restore": {"zh": "把版本变了的包装回换版本前的那样", "en": "Put the packages that changed back to their earlier versions"},
        "cleanup": {"zh": "删掉换下来的源码", "en": "Delete the source that was switched out"},
    }


# --- service_update -------------------------------------------------------------


def update(payload: dict[str, Any], locale: str, emit: Emit, *, is_cancelled: Callable[[], bool] = pinned.cancelled) -> dict[str, Any]:
    """换到一个更新的钉死版本(没说就是最新的)。换上新源码之前出错:新的那份删掉,原来的没动;换上之后出错或取消:自己换回去
    (这时不看取消 —— 半截的环境不能留),再说没成。交回换好的版本和上一版(宿主接着试起一次)。"""
    root = managed._root(payload, locale)
    if not root.is_dir():
        raise _not_installed(locale)
    log = managed._Log(str(payload.get("log") or ""))
    try:
        with managed._locked(root, locale):
            record = managed.read_record(root)
            unfinished = managed.unfinished_change(record, locale)
            if unfinished:
                raise ComfyError(unfinished)
            current = _installed(root, record, locale)
            target = str(payload.get("version") or managed.COMFYUI_VERSION)
            if target not in managed.COMFYUI_PINNED:
                raise ComfyError(say(locale, f"没有钉死 ComfyUI {target} 这个版本", f"ComfyUI {target} isn't a pinned version"))
            if not newer(target, current):
                raise ComfyError(say(locale, f"装着的已经是 {current},不比 {target} 旧", f"{current} is installed, which isn't older than {target}"))
            titles = _update_titles(current, target)
            job = _job(payload, locale, emit, record, titles=titles, steps=UPDATE_STEPS, version=target,
                       is_cancelled=is_cancelled, log=log, retry=("更新", "Update"))
            log.line(f"== {datetime.now(UTC).isoformat()} 把 ComfyUI 从 {current} 换到 {target}({root})")
            job.report.outline(set())
            freeze_name = f"pip-freeze-{current}.txt"
            try:
                for key in UPDATE_STEPS:
                    if job.is_cancelled():
                        raise pinned.Cancelled
                    log.line(f"== {titles[key]['zh']}")
                    job.report.begin(key)
                    _UPDATE_RUN[key](job, current=current, freeze_name=freeze_name)
                    job.report.finish(key)
                record.pop("updating", None)
                managed._write_record(root, record)
            except BaseException as exc:
                if record.get("updating") != target:
                    # 还没开始换(「换到一半」的标记还没写):原来那份没动,删掉解在旁边的新源码和记下的包清单就行
                    _remove_tree(root / NEXT)
                    (root / freeze_name).unlink(missing_ok=True)
                    if isinstance(exc, ComfyError):
                        raise ComfyError(say(locale, f"{exc}\n还是 {current},没动它", f"{exc}\nStill {current}; nothing changed")) from exc
                    raise
                _undo(job, current, exc)
                raise
            log.line(f"== 换到 {target} 了;{current} 留在旁边,「回到上一版」用它")
            return {"directory": str(root), "python": str(job.python), "comfyui": target, "previous": current}
    except pinned.Cancelled:
        log.line("== 取消了")
        raise
    except ComfyError as exc:
        log.line(f"== 没换成:{exc}")
        raise
    finally:
        log.close()


def _undo(job: managed._Job, current: str, cause: BaseException) -> None:
    """换上新源码之后出错或取消:换回去(不看取消),再把原因说成「没成,已经换回 x」;换回去也出错就两件都说,请人点「换回」。"""
    job.is_cancelled = pinned.never
    titles = _rollback_titles(current)
    reason = str(cause) if isinstance(cause, ComfyError) else f"{type(cause).__name__}: {cause}"
    job.log.line(f"== 没换成({reason}),换回 {current}")
    try:
        _go_back(job, titles, lambda key: job.report.progress(item=titles[key], force=True))
    except Exception as back:  # noqa: BLE001 — 换回去失败的原因要说给人听,连同最初的那个
        detail = str(back) if isinstance(back, ComfyError) else f"{type(back).__name__}: {back}"
        job.log.line(f"== 换回 {current} 也没成:{detail}")
        raise ComfyError(job.say(f"{reason}\n换回 {current} 时也出错了:{detail}。到连接页上点「换回 {current}」再试一次",
                                 f"{reason}\nGoing back to {current} failed too: {detail}. Choose “Go back to {current}” on the "
                                 f"connection page to try again")) from cause
    job.log.line(f"== 已经换回 {current}")
    if isinstance(cause, pinned.Cancelled):
        return
    raise ComfyError(job.say(f"{reason}\n已经换回 {current}(源码和依赖)", f"{reason}\nWent back to {current} (source and packages)")) from cause


def _update_disk(job: managed._Job, **_: Any) -> None:
    free = managed._free_space(job.root)
    job.log.line(f"剩余 {managed._gb(free)},换版本要 {managed._gb(UPDATE_NEED)}")
    if free < UPDATE_NEED:
        raise ComfyError(job.say(f"这块盘只剩 {managed._gb(free)},换版本要 {managed._gb(UPDATE_NEED)}。清出空间再来",
                                 f"Only {managed._gb(free)} is free on this disk; changing versions needs {managed._gb(UPDATE_NEED)}. "
                                 f"Free up space, then try again"))


def _update_download(job: managed._Job, **_: Any) -> None:
    managed._step_download(job)


def _update_extract(job: managed._Job, **_: Any) -> None:
    tarball = job.root / managed.DOWNLOADS / managed._tarball_name(job.version)
    _remove_tree(job.root / NEXT)
    pinned.unpack(tarball, job.root / NEXT, managed.COMFYUI_PINNED[job.version], job.locale, is_cancelled=job.is_cancelled)
    tarball.unlink(missing_ok=True)


def _update_freeze(job: managed._Job, *, freeze_name: str, **_: Any) -> None:
    (job.root / freeze_name).write_text(_freeze(job), encoding="utf-8")


def _update_switch(job: managed._Job, *, current: str, freeze_name: str, **_: Any) -> None:
    _switch(job, current, job.version, freeze_name)


def _update_requirements(job: managed._Job, **_: Any) -> None:
    managed._step_requirements(job)


def _update_nodes(job: managed._Job, **_: Any) -> None:
    managed._step_nodes(job)


_UPDATE_RUN: dict[str, Callable[..., None]] = {
    "disk": _update_disk,
    "download": _update_download,
    "extract": _update_extract,
    "freeze": _update_freeze,
    "switch": _update_switch,
    "requirements": _update_requirements,
    "nodes": _update_nodes,
}


# --- service_rollback -----------------------------------------------------------


def rollback(payload: dict[str, Any], locale: str, emit: Emit, *, is_cancelled: Callable[[], bool] = pinned.cancelled) -> dict[str, Any]:
    """回到上一版(或者收拾被打断的更新 / 回退)。装回依赖那一步能取消:停在那里,下次接着装回。交回换回到的版本(宿主接着试起一次)。"""
    root = managed._root(payload, locale)
    if not root.is_dir():
        raise _nothing_to_go_back_to(locale)
    log = managed._Log(str(payload.get("log") or ""))
    try:
        with managed._locked(root, locale):
            record = managed.read_record(root)
            back_to = _back_to(root, record)
            if not back_to:
                raise _nothing_to_go_back_to(locale)
            titles = _rollback_titles(back_to)
            job = _job(payload, locale, emit, record, titles=titles, steps=ROLLBACK_STEPS, version=back_to,
                       is_cancelled=is_cancelled, log=log, retry=(f"换回 {back_to}", f"Go back to {back_to}"))
            log.line(f"== {datetime.now(UTC).isoformat()} 把 ComfyUI 换回 {back_to}({root})")
            job.report.outline(set())
            phase: list[str] = []

            def announce(key: str) -> None:
                if phase:
                    job.report.finish(phase[-1])
                phase.append(key)
                log.line(f"== {titles[key]['zh']}")
                job.report.begin(key)

            current = _go_back(job, titles, announce)
            for key in ROLLBACK_STEPS:
                job.report.finish(key)
            log.line(f"== 换回 {current} 了")
            return {"directory": str(root), "python": str(job.python), "comfyui": current}
    except pinned.Cancelled:
        log.line("== 取消了:依赖还没装回去,下次「换回」接着装")
        raise
    except ComfyError as exc:
        log.line(f"== 没换回去:{exc}")
        raise
    finally:
        log.close()


__all__ = ["CARRIED", "NEXT", "PREVIOUS", "ROLLBACK_STEPS", "UPDATE_NEED", "UPDATE_STEPS", "launch", "newer", "rollback",
           "update", "versions"]
