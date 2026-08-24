"""pi 智能体运行时的适配器。

它和 `providers/` 是同一类东西 —— "怎么跟一个外部的东西说话"。区别只是那边说 HTTP、这边
起一个 Node 子进程走 stdio JSONL。此前它叫 `ai/agent/adapters.py`,和 1168 行的 host.py
(一轮对话的编排,碰库 56 次)摆在一起,而那是领域逻辑,已经搬去 domain/agent/ 和它的兄弟们
(autopilot / confirmations / memory / plan …)作伴。
"""

from app.ai.sidecar.adapters import *  # noqa: F401,F403
