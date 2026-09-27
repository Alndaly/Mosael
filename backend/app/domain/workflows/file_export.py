"""工作流的文件信封:`.mosael-workflow.json` 长什么样。

信封格式:`{format, version, name, description, workflow_revision, graph_hash, graph}`。graph 原样携带 ——
节点里引用的工作区资源(素材 / 序列 / 供应商档案等)跨工作区导入后可能悬空,这与「保存放行、就绪检查提示、
运行时拦截」的既有分层一致,导入不做资源级校验。

「导出成文件」(routes/workflows.export_one)和「发布到社区」(domain/community/publish)用的是这同一份 ——
社区上下载到的文件,和本机点「导出」拿到的是同一种东西。
"""

from __future__ import annotations

from typing import Any

from mosael_formats import workflow_file

from app.db.models import Workflow

#: 格式名、版本、后缀只定义在 mosael_formats.workflow_file(社区服务收工作流文件过的是同一份,ADR 0026)。
WORKFLOW_FILE_FORMAT = workflow_file.FORMAT
WORKFLOW_FILE_VERSION = workflow_file.VERSION
WORKFLOW_FILE_SUFFIX = workflow_file.SUFFIX


def export_payload(workflow: Workflow) -> dict[str, Any]:
    return {
        "format": WORKFLOW_FILE_FORMAT,
        "version": WORKFLOW_FILE_VERSION,
        "name": workflow.name,
        "description": workflow.description,
        "workflow_revision": workflow.revision,
        "graph_hash": workflow.graph_hash,
        "graph": workflow.graph,
    }


def ascii_file_stem(name: str) -> str:
    """文件名的 ASCII 兜底(Content-Disposition 的 `filename=`、multipart 里的文件名)。"""
    return "".join(ch if ch.isascii() and ch not in '\\/:*?"<>|' else "_" for ch in name) or "workflow"
