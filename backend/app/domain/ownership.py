"""领域数据归属地图:每张表归哪个领域模块所有。

规约(解耦候选 3):**表的行创建只能发生在拥有它的领域模块里**;跨领域需要新行时,
调用拥有方的领域函数,不直接 `Model(...)`。models.py 保持单文件(对导航友好),
边界靠这份地图 + tests/test_data_ownership_ratchet.py 的棘轮测试维持:
存量越界记录在测试的 allowlist 里只减不增,新增越界直接测试失败。

value 是「允许创建该模型实例」的路径前缀(相对 backend/,可多个:所有者 + 历史豁免
之外的合法共有者)。api/routes 与 tests 不受限——路由是薄转译层,测试要造数据。
"""

from __future__ import annotations

TABLE_OWNERS: dict[str, tuple[str, ...]] = {
    # 团队/账号
    "Workspace": ("app/api/routes/workspaces.py", "app/domain/members.py", "app/core/"),
    "User": ("app/api/routes/auth.py", "app/domain/members.py"),
    "AuthSession": ("app/api/routes/auth.py", "app/core/"),
    #: 进这个**部署**的邀请码(与 WorkspaceInvitation 进工作区是两件事,见 ADR 0008)。
    "RegistrationInvite": ("app/api/routes/auth.py",),
    "WorkspaceMember": ("app/domain/members.py", "app/api/routes/auth.py"),
    "WorkspaceInvitation": ("app/domain/members.py",),
    "OAuthIdentity": ("app/api/routes/oauth.py",),
    # 创作核心
    "Project": ("app/api/routes/projects.py", "app/domain/projects/", "app/domain/workflows/executors/content.py"),
    "Asset": ("app/domain/assets/",),
    "Sequence": ("app/domain/sequences/",),
    "Track": ("app/domain/sequences/",),
    "Clip": ("app/domain/sequences/",),
    "SequenceOperation": ("app/domain/sequences/",),
    "SequenceRevision": ("app/domain/sequences/",),
    # 逐字稿
    "Transcript": ("app/domain/transcripts/", "app/audio/"),
    "TranscriptSegment": ("app/domain/transcripts/", "app/audio/"),
    "TranscriptToken": ("app/domain/transcripts/", "app/audio/"),
    "ClipTranscriptRef": ("app/domain/transcripts/", "app/domain/sequences/"),
    # 资源库
    "Voice": ("app/domain/voices/voices.py",),
    "Lut": ("app/domain/luts.py",),
    "Font": ("app/domain/fonts.py",),
    "GeneratedAsset": ("app/domain/generation/",),
    "GenerationJob": ("app/domain/generation/",),
    "GenerationSession": ("app/domain/generation/", "app/api/routes/generation.py"),
    # 任务总线(Job/TaskEvent 只在总线创建;进度/事件请走 jobs.py 的接口)
    "Job": ("app/domain/jobs.py",),
    "TaskEvent": ("app/domain/jobs.py",),
    "Notification": ("app/domain/notifications.py",),
    # 编排
    # 「谁的」与「共享给谁」是同一张表管的,所以它只归 sharing 域写。
    # 部署级开关只归 deployment 域写 —— 「这台后端怎么对外」只该有一处答案。
    "DeploymentConfig": ("app/domain/deployment.py",),
    "ResourceShare": ("app/domain/sharing.py",),
    # 钥匙只归 provider_credentials 域写 —— 「谁的钥匙」这个问题只该有一处答案。
    "ProviderCredential": ("app/domain/provider_credentials.py", "app/domain/provider_auth.py"),
    "ScheduledTask": ("app/domain/scheduler/",),
    "ScheduledTaskRun": ("app/domain/scheduler/", "app/workers/scheduler.py"),
    "Workflow": ("app/domain/workflows/",),
    # 发布
    "PublishAccount": ("app/domain/publish/",),
    "PublishTask": ("app/domain/publish/",),
    # 浏览器自动化(RPA / 智能体)
    "BrowserProfile": ("app/domain/browser/",),
    "BrowserSession": ("app/domain/browser/",),
    "BrowserAction": ("app/domain/browser/",),
    # 配置
    "ProviderProfile": ("app/domain/providers.py", "app/api/routes/settings.py"),
    "ProviderDefault": ("app/domain/provider_defaults.py", "app/api/routes/settings.py"),
    "ProviderModel": ("app/domain/provider_models.py", "app/api/routes/settings.py"),
    "ProviderPricingRule": ("app/domain/usage.py",),
    "ProviderUsageEvent": ("app/domain/usage.py",),
    "AiRuntimeConfig": ("app/api/routes/settings.py",),
    # 单例行由 network 域按需创建(get_config),路由只负责改值。
    "NetworkConfig": ("app/domain/network.py", "app/api/routes/settings.py"),
    "TtsConfig": ("app/domain/tts_config.py",),
    # 智能体/集成
    "AgentSession": ("app/ai/agent/", "app/domain/agent/"),
    "AgentSessionGroup": ("app/domain/agent/",),
    "AgentMessage": ("app/ai/agent/", "app/domain/agent/"),
    "AgentMemory": ("app/domain/agent/",),
    "ToolConfirmation": ("app/domain/agent/",),
    "FeishuBot": ("app/integrations/feishu/",),
    "FeishuBinding": ("app/integrations/feishu/",),
    "FeishuBindCode": ("app/integrations/feishu/",),
    "PluginPackage": ("app/domain/plugins/",),
    "PluginInstance": ("app/domain/plugins/",),
    "PluginCapability": ("app/domain/plugins/",),
    "PluginPermissionGrant": ("app/domain/plugins/",),
    "PluginCredential": ("app/domain/plugins/",),
    "PluginInvocation": ("app/domain/plugins/",),
    # 知识库
}

# 路由层与测试不受限:路由是薄转译(建实体前已被鉴权链把关),测试需要自由造数据。
EXEMPT_PREFIXES: tuple[str, ...] = ("app/api/routes/", "app/db/", "app/api/schemas/")
