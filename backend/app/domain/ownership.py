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
    "WorkspaceMember": ("app/domain/members.py", "app/api/routes/auth.py"),
    "WorkspaceMemberPerm": ("app/domain/members.py",),
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
    "Voice": ("app/audio/voices.py",),
    "Lut": ("app/domain/luts.py",),
    "Font": ("app/domain/fonts.py",),
    "GeneratedAsset": ("app/domain/generation/",),
    "GenerationModel": ("app/domain/generation/",),
    "GenerationJob": ("app/domain/generation/",),
    "GenerationSession": ("app/domain/generation/", "app/api/routes/generation.py"),
    # 任务总线(Job/TaskEvent 只在总线创建;进度/事件请走 jobs.py 的接口)
    "Job": ("app/domain/jobs.py",),
    "TaskEvent": ("app/domain/jobs.py",),
    "Notification": ("app/domain/notifications.py",),
    # 编排
    "ScheduledTask": ("app/domain/scheduler/",),
    "ScheduledTaskRun": ("app/domain/scheduler/", "app/workers/scheduler.py"),
    "Workflow": ("app/domain/workflows/",),
    # 发布
    "PublishAccount": ("app/domain/publish/",),
    "PublishTask": ("app/domain/publish/",),
    # 交付(folder / webhook):从发布域拆出来的,它们不需要登录身份,也不该
    # 借道 create_account 顺手建 BrowserProfile。见 models.DeliveryTarget。
    "DeliveryTarget": ("app/domain/delivery/",),
    "DeliveryTask": ("app/domain/delivery/",),
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
    "KbEmbeddingConfig": ("app/domain/kb/",),
    "AiRuntimeConfig": ("app/api/routes/settings.py",),
    # 单例行由 network 域按需创建(get_config),路由只负责改值。
    "NetworkConfig": ("app/domain/network.py", "app/api/routes/settings.py"),
    "TtsConfig": ("app/domain/tts_config.py",),
    # 智能体/集成
    "AgentSession": ("app/ai/agent/", "app/domain/agent/"),
    "AgentMessage": ("app/ai/agent/", "app/domain/agent/"),
    "ToolConfirmation": ("app/domain/agent/",),
    "FeishuBot": ("app/integrations/feishu/",),
    "FeishuBinding": ("app/integrations/feishu/",),
    "FeishuBindCode": ("app/integrations/feishu/",),
    "Plugin": ("app/domain/plugins/",),
    "PluginPermissionGrant": ("app/domain/plugins/",),
    "PluginInvocation": ("app/domain/plugins/",),
    # 知识库
    "KbDataset": ("app/domain/kb/",),
    "KbDocument": ("app/domain/kb/",),
    "KbChunk": ("app/domain/kb/",),
}

# 路由层与测试不受限:路由是薄转译(建实体前已被鉴权链把关),测试需要自由造数据。
EXEMPT_PREFIXES: tuple[str, ...] = ("app/api/routes/", "app/db/", "app/api/schemas/")
