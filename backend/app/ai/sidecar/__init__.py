"""pi 智能体运行时的客户端(`pi_client`):起一个 Node 子进程,走 stdio JSONL 跑一轮对话、压缩上下文、
做一次无工具的补全、刷新订阅令牌。

它和 `providers/` 是同一类东西 —— "怎么跟一个外部的东西说话" —— 区别只是那边说 HTTP、这边起子进程。
这里只写说明,不转发:调用方从 `app.ai.sidecar.pi_client` 取。
"""
