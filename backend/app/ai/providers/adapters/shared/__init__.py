"""只有适配器用的实现辅助:HTTP 失败归类(`errors`)、异步任务轮询(`polling`)、音频产出落盘(`audio_files`)。

契约(`contracts/`)只放领域也要认的东西 —— 请求、结果、角色、适配器基类;这些辅助是「怎么跟一家说话」的
实现细节,放在 adapters 底下,领域就碰不到它们(见 tests/test_ai_is_infrastructure)。
"""
