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
或进程协议；这些全部留在 Gateway Module 的 Implementation 中。

**安全不变量**：Gateway 不监听网络端口；不接受调用方提供的任意 `base_url`；OAuth Token 不进入浏览器、
响应或日志；服务令牌短期有效、绑定凭据主人并在补全结束后立即撤销；Gateway 永远没有智能体工具。OAuth
失效时明确要求重新登录，不得静默切换模型或借用他人凭据。

**Considered options**：启动本地 OpenAI-compatible HTTP 代理——拒绝，新增可探测端口与第二套鉴权却没有
跨进程部署收益；让工作流启动完整 Agent——拒绝，工具循环和会话记忆破坏节点的确定性；在 Python 重写
各家 OAuth 刷新——拒绝，六家协议会与 pi Provider 漂移。
