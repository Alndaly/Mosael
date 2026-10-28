#: 静态目录(能力描述符、内置模型、种类)不在这里:它住在 domain/generation_catalog,供应商和实体也要查它,
#: 放在生成包里会让它们为了一张表反过来依赖生成域。
from app.domain.generation.operations import create_generation_job
#: 选项列表是 db 感知的,住在集成缝上;catalog 保持纯静态目录,不向上伸手(分层测试钉着)。
from app.domain.generation.resolution import generation_options

__all__ = [
    "create_generation_job",
    "generation_options",
]
