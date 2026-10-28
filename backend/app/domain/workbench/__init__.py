"""工作台领域的确认工具。

放在 `app.domain.workbench` 而不是通用 `app.domain.agent.confirmable`：ComfyUI 确认卡要调用
workbench/agent.py / server_workflows，和通用智能体包属于不同依赖方向。import 这个包就是登记。
"""

from app.domain.workbench import confirmable  # noqa: F401  (registration)
