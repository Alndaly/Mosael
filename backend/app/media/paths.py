from __future__ import annotations

from pathlib import Path

from app.core.config import settings


def asset_dir(workspace_id: str, asset_id: str) -> Path:
    return settings.media_dir / "assets" / workspace_id / asset_id


def asset_key(workspace_id: str, asset_id: str, filename: str) -> str:
    return str(Path("media") / "assets" / workspace_id / asset_id / filename)


def voice_dir(workspace_id: str, voice_id: str) -> Path:
    return settings.media_dir / "voices" / workspace_id / voice_id


def voice_key(workspace_id: str, voice_id: str, filename: str) -> str:
    return str(Path("media") / "voices" / workspace_id / voice_id / filename)


def lut_dir(workspace_id: str, lut_id: str) -> Path:
    return settings.media_dir / "luts" / workspace_id / lut_id


def lut_key(workspace_id: str, lut_id: str, filename: str) -> str:
    return str(Path("media") / "luts" / workspace_id / lut_id / filename)


def font_dir(workspace_id: str, font_id: str) -> Path:
    return settings.media_dir / "fonts" / workspace_id / font_id


def font_key(workspace_id: str, font_id: str, filename: str) -> str:
    return str(Path("media") / "fonts" / workspace_id / font_id / filename)


#: 3D 模型的字节。**按工作区分目录**(模型归工作区,见 db.model_slices.scenes.Scene3DModel);
#: 放在 media/ 下面是因为备份打包的正是 media(见 domain/data_management 的 BACKUP_DIRECTORIES)
#: —— 另起一个顶层目录的话,备份会悄悄不含 3D 模型,而这种缺失只有在恢复之后才发现。
def scene_model_dir(workspace_id: str) -> Path:
    return settings.media_dir / "scene-models" / workspace_id


def scene_preview_dir(workspace_id: str) -> Path:
    """画板上 3D 场景格的预览图缓存(按场景修订号,见 domain/scenes/operations.scene_overview_image)。"""
    return settings.media_dir / "scene-previews" / workspace_id


def scene_model_key(workspace_id: str, filename: str) -> str:
    return str(Path("media") / "scene-models" / workspace_id / filename)


#: media/ 下**按工作区分目录**的几类东西。删工作区时整个清掉的就是这几个目录(见 domain/storage_cleanup),对账也照它找
#: 「工作区已经不在了的目录」。新加一类按工作区存的东西就加在这里 —— 漏了的话删工作区时它的文件留在盘上,
#: 而行早就跟着外键走了(tests/test_deleted_workspaces_leave_no_files.py 钉着:上面每个按工作区分的 *_dir 都要在这张表里)。
WORKSPACE_MEDIA_CATEGORIES = ("assets", "voices", "luts", "fonts", "scene-models", "scene-previews")


def workspace_media_dirs(workspace_id: str) -> tuple[Path, ...]:
    """这个工作区在 media/ 下的全部目录(素材、音色、LUT、字体、3D 模型、场景预览)。"""
    return tuple(settings.media_dir / category / workspace_id for category in WORKSPACE_MEDIA_CATEGORIES)


class StorageKeyError(ValueError):
    """存储键逃出了数据目录。键都由上面这些 *_key 在服务端生成,碰到它只可能是 bug 或被塞了数据。"""


def resolve_key(key: str) -> Path:
    """存储键 → 数据目录里的文件。

    **只认数据目录里的相对路径。** `data_dir / "/Users/x/.ssh/id_rsa"` 在 Python 里就是那个绝对
    路径本身,`../` 也能一路走出去 —— 素材的文件接口按键把文件原样发出去,一个逃出去的键就是
    一条读这台电脑上任意文件的路,绕过了 domain/host_files 那道闸。判的是键的写法(不展开软链接):
    数据目录底下的软链接是部署自己放的,不归这里管。
    """
    parts = Path(key).parts
    if Path(key).is_absolute() or ".." in parts:
        raise StorageKeyError(key)
    return settings.data_dir / key

