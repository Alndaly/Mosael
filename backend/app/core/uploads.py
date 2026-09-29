"""「上传的文件」:领域函数收的是这个协议,不是 web 框架的类型。

路由传进来的 fastapi.UploadFile 按结构就满足它;非 HTTP 的调用方(测试、工作流节点)随手造一个也行。
"""

from __future__ import annotations

from typing import BinaryIO, Protocol


class UploadedFile(Protocol):
    filename: str | None
    content_type: str | None
    file: BinaryIO
