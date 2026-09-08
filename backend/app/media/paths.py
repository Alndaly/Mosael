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


#: 3D 模型的字节。**按场景分目录**,删场景时一次 rmtree 就干净了;而放在 media/ 下面是因为
#: 备份打包的正是 media(见 domain/data_management 的 BACKUP_DIRECTORIES)—— 另起一个顶层
#: 目录的话,备份会悄悄不含 3D 模型,而这种缺失只有在恢复之后才发现。
def scene_model_dir(workspace_id: str, scene_id: str) -> Path:
    return settings.media_dir / "scene-models" / workspace_id / scene_id


def scene_model_key(workspace_id: str, scene_id: str, filename: str) -> str:
    return str(Path("media") / "scene-models" / workspace_id / scene_id / filename)


def resolve_key(key: str) -> Path:
    return settings.data_dir / key

