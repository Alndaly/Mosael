# Provider 以能力契约、连接 Adapter、统一 Registry 三层组织

## Context

Provider 同时存在两条正交的分类轴：上层调用方关心模型具备图像、视频或语音哪种能力；底层实现关心
API Key、Base URL、请求字段、轮询和媒体传输属于哪套连接协议。旧目录把两条轴放在同一级：有些目录按
能力命名，有些文件按供应商或平台命名，公共 `__init__.py` 又同时定义 Interface、导入 Implementation
并完成注册。Evolink、ComfyUI 和百炼等跨能力连接因此要么被拆散共享协议，要么继续长成单文件。

## Decision

Provider 使用三个 Module：

1. `app/ai/providers/contracts/` 按能力定义 Interface。契约不得依赖具体 Adapter 或 Registry。
2. `app/ai/providers/adapters/` 先按平台/企业形成命名空间，再按真正独立的产品协议族组织
   Implementation；同一协议族支持多种能力时，才在其下以 `image.py`、`video.py`、`speech.py`
   拆分。目录表达归属，Adapter 边界由认证、端点、任务协议和错误语义决定。
3. `app/ai/providers/registry.py` 是内置 Adapter 的唯一装配入口，精确登记 `(vendor, kind)` 和语音引擎
   id；重复键直接导致启动失败，不能静默覆盖。

`app.ai.providers` 保持领域 Module 使用的稳定公共 Interface。领域 Module 不直接选择具体 Adapter；
只有供应商专属的配置/诊断路由和针对 Implementation 的测试可以直接引用 `adapters`。

架构棘轮验证依赖方向和根目录角色，防止三层重新混合。

ByteDance 是这个规则的校准样例：

- `adapters/bytedance/ark/{image,video}.py` 是方舟 Ark 的 Seedream / Seedance；
- `adapters/bytedance/volcano/{speech,podcast,podcast_protocol}.py` 是语音技术控制台的同步 TTS 与
  播客 WebSocket；
- 三者属于同一企业，但凭据和协议不可互换，因此持久化 vendor id 继续使用 `bytedance`、`volcano`
  与 `volcano-podcast`。目录路径不充当数据库主键。

阿里云图像、视频和语音共享一套百炼 DashScope 连接协议，因此统一在
`adapters/alibaba/dashscope/{image,video,speech}.py`。

Evolink 与 ComfyUI 相反：它们各自用一套生成协议横跨图像和视频，因此保留一个较深的
`generation.py` Implementation，由构造参数选择 `media_kind`，不复制两套 HTTP 客户端。

## Consequences

- 能力扩展发生在契约 Seam，供应商协议变化留在对应 Adapter，具有更好的 Locality。
- Evolink、ComfyUI 等平台协议可以复用认证、轮询和媒体传输，同时仍把不同能力的字段翻译拆开。
- Registry 给调用方提供较小 Interface，并在启动阶段暴露冲突，增加测试和运行时 Leverage。
- `GenerationAdapterContext` 使用 `connection_id` / `vendor_id` / `configured_model_id` / `options`，
  不再把数据库 Profile、供应商和 Adapter 配置混成含糊属性。
- 直接引用旧 Implementation 路径的内部代码和测试必须迁移；这是一次有意的内部路径变更，公共入口不变。

## Rejected alternatives

- **纯能力目录**（`providers/image/<vendor>.py`）：会把同一连接的鉴权、Endpoint、轮询与媒体传输拆散。
- **所有供应商都挤在 Adapter 根目录的单文件**（旧式 `adapters/evolink.py`）：企业、产品协议与能力边界
  无法从路径读取，跨能力平台也会持续长成巨型浅 Module。
- **每种能力独立 Registry**：调用方需要学习多套选择规则，且无法统一拒绝重复或冲突的 Adapter 登记。
