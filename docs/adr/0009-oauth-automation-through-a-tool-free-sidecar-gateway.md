# OAuth 自动化走无工具 sidecar Gateway，不暴露反向代理

画板写作与工作流 LLM 需要确定性的单次补全，但订阅授权的端点、OAuth 刷新协议和模型目录只存在于
pi Provider。要求用户补 `base_url` 是错误修复路径；把 OAuth Token 包成一个监听端口的通用反向代理，
则会扩大凭据泄露、SSRF、跨用户调用与工具越权的攻击面，并违背 ADR-0001 的本地优先卫星进程形态。

我们在现有 Python ↔ sidecar JSONL/stdin **Seam** 增加 `gateway_complete`：后端仍是事实源，按当前用户
解析连接与模型，铸造短期服务令牌；sidecar 用 pi Provider 完成 OAuth 解析/刷新，但只调用一次
`completeSimple`，上下文没有工具、没有会话状态、没有子智能体。刷新写回继续复用已有 acquire → commit
租约，多个画板、工作流和智能体并发时不会拿同一枚 refresh token 互相覆盖。

模型选择器使用 `automation` 执行面：有效 API Key 连接映射到 `direct` Adapter，已登录 OAuth 连接映射
到 `gateway` Adapter。调用方只学习统一的 `ai_chat.chat` Interface，不接触 OAuth 凭据、pi Provider id
或进程协议；这些全部留在 Gateway Module 的 Implementation 中。能力与执行面是两条独立的轴：
`chat` / `vision` 决定模型是否适用，`agent` / `direct` / `gateway` 决定凭据、状态和工具如何运行。

当前调用矩阵：

| 调用方 | 执行面 | 语义 |
| --- | --- | --- |
| AI Studio 智能体 | `agent` | 完整 pi Agent：会话、记忆、工具循环、子智能体 |
| 无限画布写作/看图 | `automation` | 无状态单次补全；按连接分派 `direct` / `gateway` |
| 工作流 LLM 节点 | `automation` | 无状态单次补全；当前只组装文本消息 |
| 素材分析 API / `analyze_asset` | `direct` | 独立选模，不继承当前智能体模型，也不使用 OAuth Gateway |

Gateway 接受 system/user/assistant 文本和 `image_url` data URI。图片至多 8 张，编码后每张至多 8 MiB；
非 system 角色会连同角色标签折叠成一次提示词。它不接受 `video_url`，不复用调用方的 HTTP client，
也不保留跨请求上下文。sidecar 依据模型目录确认视觉能力后才把图片交给 Provider。

`target_for(..., surface="automation")` 为一次 Gateway 调用铸造并提交短期服务令牌，`chat(...)` 在
`finally` 中立即撤销。因此这两个 Interface 必须紧邻使用，不能把带 Gateway 令牌的 `ChatTarget` 缓存、
跨任务传递或只构造不消费；进程中断时由令牌 TTL 兜底。这个顺序是 Gateway 的安全边界，不是普通
配置解析的无副作用语义。

**安全不变量**：Gateway 不监听网络端口；不接受调用方提供的任意 `base_url`；OAuth Token 不进入浏览器、
响应或日志；服务令牌短期有效、绑定凭据主人并在补全结束后立即撤销；Gateway 永远没有智能体工具。OAuth
失效时明确要求重新登录，不得静默切换模型或借用他人凭据。

**非目标**：Gateway 不是可对外发布的 OpenAI-compatible API，也不是 OAuth 反向代理；它不替代完整
Agent，不为独立素材分析兜底，也不允许浏览器或插件直接拿服务令牌。若未来确有跨进程部署需求，应另写
ADR 定义调用方身份、租户隔离、目标白名单、配额与审计，不能直接给当前 stdin Seam 加监听端口。

**Considered options**：启动本地 OpenAI-compatible HTTP 代理——拒绝，新增可探测端口与第二套鉴权却没有
跨进程部署收益；让工作流启动完整 Agent——拒绝，工具循环和会话记忆破坏节点的确定性；在 Python 重写
各家 OAuth 刷新——拒绝，六家协议会与 pi Provider 漂移。
