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


def resolve_key(key: str) -> Path:
    return settings.data_dir / key

