"""本机服务的错误:带文案 key(`localServiceErr_*`,见 core/messages/plugins),`status` 是翻成 HTTP 时的状态码。

它是一种 `PluginDomainError`:本机服务起不来,这个插件连接就用不了 —— 模型库、工作流库、生成、智能体调插件工具
这些入口本来就把插件域的错误原话交给界面(422)、记进任务失败原因,一个都不用为它另加一支。
"""

from __future__ import annotations

from app.domain.plugins.errors import PluginDomainError


class LocalServiceError(PluginDomainError):
    """本机服务做不成:没配、目录被别的连接占着、端口被占、起不来…… `status` 给本机服务自己的路由翻状态码用。"""

    def __init__(self, key: str, *, status: int = 409, **params: object) -> None:
        super().__init__(key, **params)
        self.status = status


__all__ = ["LocalServiceError"]
