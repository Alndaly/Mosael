# Provider 以能力契约、连接 Adapter、统一 Registry 三层组织

## Context

Provider 同时存在两条正交的分类轴：上层调用方关心模型具备图像、视频或语音哪种能力；底层实现关心
API Key、Base URL、请求字段、轮询和媒体传输属于哪套连接协议。旧目录把两条轴放在同一级：有些目录按
能力命名，有些文件按供应商或平台命名，公共 `__init__.py` 又同时定义 Interface、导入 Implementation
并完成注册。Evolink、ComfyUI 和百炼等跨能力连接因此要么被拆散共享协议，要么继续长成单文件。

## Decision

Provider 使用三个 Module：

1. `app/ai/providers/contracts/` 按能力定义 Interface。契约不得依赖具体 Adapter 或 Registry。
2. `app/ai/providers/adapters/` 按技术连接协议组织 Implementation。同一连接支持多种能力时，在自己的
   目录内以 `image.py`、`video.py`、`speech.py` 拆分；分类依据是认证、端点和协议，不是企业归属。
3. `app/ai/providers/registry.py` 是内置 Adapter 的唯一装配入口，精确登记 `(vendor, kind)` 和语音引擎
   id；重复键直接导致启动失败，不能静默覆盖。

`app.ai.providers` 保持领域 Module 使用的稳定公共 Interface。领域 Module 不直接选择具体 Adapter；
只有供应商专属的配置/诊断路由和针对 Implementation 的测试可以直接引用 `adapters`。

架构棘轮验证依赖方向和根目录角色，防止三层重新混合。

## Consequences

- 能力扩展发生在契约 Seam，供应商协议变化留在对应 Adapter，具有更好的 Locality。
- Evolink、ComfyUI 等平台协议可以复用认证、轮询和媒体传输，同时仍把不同能力的字段翻译拆开。
- Registry 给调用方提供较小 Interface，并在启动阶段暴露冲突，增加测试和运行时 Leverage。
- 直接引用旧 Implementation 路径的内部代码和测试必须迁移；这是一次有意的内部路径变更，公共入口不变。

## Rejected alternatives

- **纯能力目录**（`providers/image/<vendor>.py`）：会把同一连接的鉴权、Endpoint、轮询与媒体传输拆散。
- **纯供应商单文件**（`providers/evolink.py`）：跨能力平台会持续长成巨型浅 Module。
- **每种能力独立 Registry**：调用方需要学习多套选择规则，且无法统一拒绝重复或冲突的 Adapter 登记。
