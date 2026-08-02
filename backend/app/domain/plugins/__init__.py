"""插件体系:包 → 实例 → 能力。

- `manifest`  清单解析(文件长什么样 → 代码用什么形状),兼容旧写法
- `packages`  磁盘目录 ↔ 包记录:扫描、清理、卸载
- `instances` 一次接入:配置、凭据、权限、能力开关
- `tools`     有哪些工具、暴露哪些、怎么调一次(**唯一执行路径**)
- `nodes`     插件自带的工作流节点
- `runtime` / `mcp_bridge`  两种执行形态的传输层

设计与取舍见 docs/PLUGIN_ARCHITECTURE.md 与 docs/adr/0005-*。
"""

from app.domain.plugins.errors import PluginDomainError

__all__ = ["PluginDomainError"]
