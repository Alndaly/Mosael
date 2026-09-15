from app.domain.generation.catalog import (
    CAPABILITY_PROFILES,
    builtin_models_for,
    capabilities_are_known,
    capabilities_for,
    profile_id_for,
    resolve_capability_ref,
)
from app.domain.generation.operations import create_generation_job
#: 选项列表是 db 感知的,住在集成缝上;catalog 保持纯静态目录,不向上伸手(分层测试钉着)。
from app.domain.generation.resolution import generation_options

__all__ = [
    "CAPABILITY_PROFILES",
    "builtin_models_for",
    "capabilities_are_known",
    "capabilities_for",
    "create_generation_job",
    "generation_options",
    "profile_id_for",
    "resolve_capability_ref",
]
