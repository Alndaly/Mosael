"""共用的模型文件夹(ADR 0041 拍板 5):本机这台 ComfyUI 也读别处已有的模型文件夹 —— A1111 / Forge 的 `models`、另一份 ComfyUI 的
`models`、卸载时保留下来的那一份 —— 不拷第二份。

**走 ComfyUI 自己的 `--extra-model-paths-config <文件>`**:那份 yaml 写在**宿主给的目录**里(`config_dir`,
`<数据目录>/local-services/<连接>/extra_model_paths.yaml`),「用我自己装的」和「让 Mosael 装」都一样 —— 不往人家的 ComfyUI
目录里写任何东西(「不改你的安装」)。ComfyUI 只读这些文件夹;**模型库下载的新文件仍落在它自己的 models**(见 install._local_dir,
宿主经环境变量 `MOSAEL_LOCAL_SERVICE_SHARED` 告诉插件哪几处是共用的),写回预览图、按哈希找(pysssss 会在模型旁边写 `.sha256`)
也不碰共用的那几处(见 previews、lookup)。

**认得两种样子**(和 ComfyUI 自带的 extra_model_paths.yaml.example 那两段同一张对照表):

- ComfyUI 的 `models`(选 ComfyUI 目录本身也行,认里面的 `models`):每个子目录对上同名的模型目录;`clip` → text_encoders、
  `unet` → diffusion_models(ComfyUI 的老名字)、`t2i_adapter` → controlnet;
- A1111 / Forge(选 webui 目录或它的 `models` 都行):`models/Stable-diffusion` → checkpoints 和 configs、`models/Lora` 和
  `models/LyCORIS` → loras、`models/VAE` → vae、`models/ESRGAN` 等 → upscale_models、`embeddings`、`models/hypernetworks`、
  `models/ControlNet`,Forge 的 `models/text_encoder` → text_encoders。

    {"op": "service_model_folders", "directory", "shared_models": [...]}
        → 每一处认成了哪种、对上哪几个模型目录、有什么问题;ComfyUI 在跑的话,它加载了没有、从那里看到几个模型
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lines import ComfyError, say
from model_files import files_in, folder_info

#: 宿主告诉插件「这几处是共用的模型文件夹,只读」(JSON 列表,绝对路径)。
SHARED_ENV = "MOSAEL_LOCAL_SERVICE_SHARED"
#: 宿主给的目录里那份配置的名字(ComfyUI 的叫法)。
CONFIG_NAME = "extra_model_paths.yaml"
#: ComfyUI 的模型文件夹里常见的子目录:有其中之一就认它是。
COMFY_MARKERS = ("checkpoints", "loras", "vae", "diffusion_models", "unet", "text_encoders", "clip", "controlnet",
                 "upscale_models", "embeddings", "clip_vision")
#: ComfyUI 的子目录 → 模型目录:老名字和 extra_model_paths.yaml.example 里并到别处的那一个,其余同名。
COMFY_ALIASES = {"clip": "text_encoders", "unet": "diffusion_models", "t2i_adapter": "controlnet"}
#: A1111 / Forge(相对 webui 目录)→ 模型目录。
A1111_MAP = (
    ("checkpoints", "models/Stable-diffusion"), ("configs", "models/Stable-diffusion"), ("vae", "models/VAE"),
    ("loras", "models/Lora"), ("loras", "models/LyCORIS"), ("upscale_models", "models/ESRGAN"),
    ("upscale_models", "models/RealESRGAN"), ("upscale_models", "models/SwinIR"), ("embeddings", "embeddings"),
    ("hypernetworks", "models/hypernetworks"), ("controlnet", "models/ControlNet"), ("text_encoders", "models/text_encoder"),
)
#: 最多共用几处。
MAX_FOLDERS = 20


@dataclass
class Shared:
    """认出来的一处:`layout` 是 `comfyui` / `a1111`;`folders` 是模型目录 → 那里的绝对路径(可能几处)。认不出时 `problem` 说为什么。"""

    path: str
    layout: str = ""
    root: Path | None = None
    folders: dict[str, list[str]] = field(default_factory=dict)
    problem: dict[str, str] | None = None


def _key(path: Path | str) -> str:
    """比较路径用:规整写法、大小写不敏感的盘上抹平(和 ComfyUI 记路径的 os.path.normpath 同一种写法,再解开符号链接)。"""
    return os.path.normcase(os.path.realpath(os.path.normpath(str(path))))


def _inside(path: Path | str, root: Path | str) -> bool:
    child, parent = _key(path), _key(root)
    return child == parent or child.startswith(parent.rstrip(os.sep) + os.sep)


def _subdirs(folder: Path) -> list[Path]:
    try:
        return sorted(one for one in folder.iterdir() if one.is_dir() and not one.name.startswith("."))
    except OSError:
        return []


def _comfy_models(path: Path) -> Path | None:
    """ComfyUI 的模型文件夹:选的就是它,或者选的是 ComfyUI 目录(里面的 `models`)。"""
    for candidate in (path, path / "models"):
        names = {one.name.lower() for one in _subdirs(candidate)}
        if names & set(COMFY_MARKERS):
            return candidate
    return None


def _a1111_root(path: Path) -> Path | None:
    """A1111 / Forge 的 webui 目录:选的是它(有 `models/Stable-diffusion`),或者选的是它的 `models`。"""
    if (path / "models" / "Stable-diffusion").is_dir():
        return path
    if path.name.lower() == "models" and (path / "Stable-diffusion").is_dir():
        return path.parent
    return None


def inspect(raw: str, locale: str, *, own_models: Path | None = None) -> Shared:
    """认这一处:是哪种、对上哪几个模型目录。`own_models` 是这台 ComfyUI 自己的模型文件夹 —— 共用它自己(或者它在共用的那一处
    里面)没有意义,还会让同一个文件列两遍。"""
    text = (raw or "").strip()
    found = Shared(path=text)
    path = Path(text).expanduser() if text else Path()
    if not text or not path.is_absolute():
        found.problem = {"zh": f"要一个完整的路径:{text}", "en": f"A full path is needed: {text}"}
        return found
    if not path.is_dir():
        found.problem = {"zh": f"这台机器上没有这个文件夹:{text}", "en": f"There's no such folder on this machine: {text}"}
        return found
    if own_models is not None and (_inside(path, own_models) or _inside(own_models, path)):
        found.problem = {"zh": f"这就是它自己的模型文件夹(或者包着它):{text}",
                         "en": f"This is its own models folder (or contains it): {text}"}
        return found
    root = _a1111_root(path)
    if root is not None:
        found.layout, found.root = "a1111", root
        for folder, relative in A1111_MAP:
            target = root.joinpath(*relative.split("/"))
            if target.is_dir():
                found.folders.setdefault(folder, []).append(os.path.normpath(str(target)))
        return found
    models = _comfy_models(path)
    if models is not None:
        found.layout, found.root = "comfyui", models
        for sub in _subdirs(models):
            folder = COMFY_ALIASES.get(sub.name.lower(), sub.name)
            found.folders.setdefault(folder, []).append(os.path.normpath(str(sub)))
        return found
    found.problem = {
        "zh": f"认不出这是模型文件夹:要 ComfyUI 的 models(里面有 checkpoints、loras 这类子目录),或者 A1111 / Forge 的 webui 目录"
              f"(有 models/Stable-diffusion):{text}",
        "en": f"This doesn't look like a models folder: pick ComfyUI's models (with subfolders like checkpoints and loras) or "
              f"an A1111 / Forge webui folder (with models/Stable-diffusion): {text}",
    }
    return found


def config(found: list[Shared]) -> dict[str, dict[str, str]]:
    """extra_model_paths.yaml 的内容:一处一段,每个模型目录一行,几处路径用换行连着(ComfyUI 按 `\\n` 拆)。路径都是绝对的,
    不用 `base_path`(ComfyUI 会对它做 expandvars,路径里有 `$` 的会被改掉)。"""
    sections: dict[str, dict[str, str]] = {}
    for index, one in enumerate(item for item in found if item.problem is None and item.folders):
        sections[f"mosael_shared_{index + 1}"] = {folder: "\n".join(paths) for folder, paths in one.folders.items()}
    return sections


def write_config(config_dir: str, found: list[Shared]) -> Path | None:
    """把配置写进宿主给的目录(先写临时文件再改名);一处能用的都没有就删掉上一份,交回 None(不加那个参数)。

    写的是 JSON —— 它也是合法的 YAML(ComfyUI 用 yaml.safe_load 读),插件只有标准库,不必自己拼 YAML 的转义。"""
    if not config_dir:
        return None
    target = Path(config_dir) / CONFIG_NAME
    sections = config(found)
    if not sections:
        target.unlink(missing_ok=True)
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{CONFIG_NAME}.tmp")
    temporary.write_text("# Mosael 写的(本机服务的共用模型文件夹),每次启动前重写;别手改\n"
                         + json.dumps(sections, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)
    return target


def shared_roots() -> list[str]:
    """宿主说的共用的那几处(没有本机服务、或者没共用是空的)。"""
    try:
        value = json.loads(os.environ.get(SHARED_ENV) or "[]")
    except ValueError:
        return []
    return [str(one) for one in value if isinstance(one, str) and one] if isinstance(value, list) else []


def in_shared(path: Path | str, roots: list[str] | None = None) -> bool:
    """这个路径在不在共用的哪一处里面。认法和写配置时一样:A1111 选的是 `models` 时,`embeddings` 在它上一层 —— 所以
    按「认出来的样子」的根比,不只按人选的那个路径比。"""
    for raw in shared_roots() if roots is None else roots:
        if _inside(path, raw):
            return True
        root = _a1111_root(Path(raw))
        if root is not None and _inside(path, root):
            return True
    return False


def shared_file(comfy: Any, folder: str, name: str) -> Path | None:
    """这个模型文件在共用的哪一处里面时,交回它在磁盘上的位置;不在共用的那几处(或者根本没共用)是 None。
    按 ComfyUI 报的路径找(`/experiment/models` 的第几处 + 文件的 `pathIndex`)。"""
    roots = shared_roots()
    if not roots:
        return None
    info = folder_info(comfy) or {}
    paths = info.get(folder) or []
    wanted = name.replace("\\", "/")
    for item in files_in(comfy, folder):
        if str(item.get("name") or "").replace("\\", "/") != wanted:
            continue
        index = int(item.get("pathIndex") or 0)
        if index < len(paths):
            location = Path(paths[index]).joinpath(*wanted.split("/"))
            return location if in_shared(location, roots) else None
    return None


def refuse_write(location: Path, locale: str) -> ComfyError:
    """要往共用的文件夹里写(存预览图)时说的那一句。"""
    return ComfyError(say(locale, f"这个模型在共用的模型文件夹里,Mosael 不往那里写(那是别处的文件夹,只读):{location}",
                          f"This model is in a shared models folder, which Mosael never writes to (it belongs elsewhere and "
                          f"is read-only): {location}"))


# --- op: service_model_folders ----------------------------------------------------

LAYOUT_LABELS = {"comfyui": {"zh": "ComfyUI 的模型文件夹", "en": "ComfyUI models folder"},
                 "a1111": {"zh": "A1111 / Forge", "en": "A1111 / Forge"}}


def _loaded_counts(comfy: Any, found: list[Shared]) -> dict[str, tuple[bool, int]] | None:
    """在跑的那台 ComfyUI 看到了哪几处、每处几个模型(按 `/experiment/models` 报的路径对:每个文件属于第几处路径)。
    连不上(没在跑)是 None。"""

    try:
        info = folder_info(comfy)
    except ComfyError:
        return None
    if info is None:
        return None
    out: dict[str, tuple[bool, int]] = {}
    for one in found:
        dirs = {_key(path) for paths in one.folders.values() for path in paths}
        loaded = any(_key(path) in dirs for paths in info.values() for path in paths)
        count = 0
        if loaded:
            for folder, paths in info.items():
                indexes = {index for index, path in enumerate(paths) if _key(path) in dirs}
                if not indexes:
                    continue
                count += sum(1 for item in files_in(comfy, folder) if int(item.get("pathIndex") or 0) in indexes)
        out[one.path] = (loaded, count)
    return out


def model_folders(payload: dict[str, Any], locale: str, *, comfy: Any = None) -> dict[str, Any]:
    """连接页上「共用的模型文件夹」那一块:每一处认成什么、对上哪几个模型目录、有什么问题;在跑的话它加载了没有、看到几个模型
    (刚加的要重启才加载)。"""
    import service  # service 也要用这里(起的时候写配置):在这里才取,不成环

    raw_folders = [str(one) for one in payload.get("shared_models") or [] if str(one).strip()][:MAX_FOLDERS]
    directory = str(payload.get("directory") or "").strip()
    layout = service.find_layout(Path(directory).expanduser()) if directory else None
    own = layout.root / "models" if layout is not None else None
    found = [inspect(one, locale, own_models=own) for one in raw_folders]
    counts = _loaded_counts(comfy, found) if comfy is not None else None
    folders = []
    for one in found:
        loaded, models = counts.get(one.path, (False, 0)) if counts is not None else (None, None)
        folders.append({
            "path": one.path,
            "ok": one.problem is None,
            "layout": LAYOUT_LABELS.get(one.layout) or "",
            "folders": sorted(one.folders),
            "problem": one.problem or "",
            "loaded": loaded,
            "models": models,
        })
    return {"folders": folders, "running": counts is not None}


__all__ = ["CONFIG_NAME", "SHARED_ENV", "Shared", "config", "in_shared", "inspect", "model_folders", "refuse_write", "shared_file",
           "shared_roots",
           "write_config"]
