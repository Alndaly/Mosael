"""一个装好的 ComfyUI 摆在哪、是哪一种样子 —— 认目录这件事本身(纯函数 + 一张表,只有标准库)。

`Layout` 说「哪一层是 ComfyUI 的根、Windows 便携版的外层在哪」;`LAYOUT_LABELS` 是这两种样子给人看的
名字。`service`(认目录、怎么起、补装 pysssss)与 `shared_models`(共用的模型文件夹要问「它自己的 models
在哪」)都要这一样东西,所以它住在两者**下面**这个叶子里:`service` 认识 `shared_models`,反过来不认识 ——
先前那条反向依赖(函数内 `import service`)把这两个模块圈成了一个环。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Layout:
    """认出来的 ComfyUI:`root` 是有 main.py 和 comfy/ 的那一层;便携版时 `portable` 是外层(有 python_embeded/)。"""

    root: Path
    portable: Path | None = None


def find_layout(directory: Path) -> Layout | None:
    """用户选的目录 → ComfyUI 在哪。Windows 便携版的两种选法都认:外层的 `ComfyUI_windows_portable`(里面是 `ComfyUI/`
    和 `python_embeded/`),或者里面那层 `ComfyUI/`。"""
    for candidate in (directory, directory / "ComfyUI"):
        if (candidate / "main.py").is_file() and (candidate / "comfy").is_dir():
            outer = candidate.parent if candidate == directory else directory
            return Layout(candidate, outer if (outer / "python_embeded").is_dir() else None)
    return None


#: 认出来的这两种样子给人看的名字(`service_model_folders` 每一处都带上它)。
LAYOUT_LABELS = {"comfyui": {"zh": "ComfyUI 的模型文件夹", "en": "ComfyUI models folder"},
                 "a1111": {"zh": "A1111 / Forge", "en": "A1111 / Forge"}}
