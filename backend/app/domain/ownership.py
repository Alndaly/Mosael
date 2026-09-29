"""领域数据归属地图:每张表归哪个领域模块所有。

规约(解耦候选 3):**表的行创建只能发生在拥有它的领域模块里**;跨领域需要新行时,
调用拥有方的领域函数,不直接 `Model(...)`。ORM 可按领域切片,但调用方只认统一装配入口
`app.db.models`;数据归属仍靠这份地图 + tests/test_data_ownership_ratchet.py 的棘轮测试维持:
存量越界记录在测试的 allowlist 里只减不增,新增越界直接测试失败。

value 是「允许创建该模型实例」的路径前缀(相对 backend/,可多个:所有者 + 历史豁免
之外的合法共有者)。测试不受限(要造数据);路由不豁免,见文末 EXEMPT_PREFIXES。
每一条前缀都必须真的存在(棘轮会查)—— 指向幽灵的登记等于没有登记。
"""

from __future__ import annotations

TABLE_OWNERS: dict[str, tuple[str, ...]] = {
    # 团队/账号
    "Workspace": ("app/domain/members.py",),
    "User": ("app/domain/members.py",),
    "AuthSession": ("app/api/routes/auth.py", "app/core/"),
    #: 进这个**部署**的邀请码(与 WorkspaceInvitation 进工作区是两件事,见 ADR 0008)。
    "RegistrationInvite": ("app/api/routes/auth.py",),
    "WorkspaceMember": ("app/domain/members.py",),
    "WorkspaceInvitation": ("app/domain/members.py",),
    "OAuthIdentity": ("app/api/routes/oauth.py",),
    # 创作核心
    "Project": ("app/domain/projects/",),
    "Asset": ("app/domain/assets/",),
    #: 文档的解析结果(ADR 0031)只归文档域写。
    "AssetExtraction": ("app/domain/documents/",),
    # 资产库(ADR 0027):人物 / 场景 / 道具与它们的参考图只归 entities 域写。
    "Entity": ("app/domain/entities/",),
    "EntityReference": ("app/domain/entities/",),
    "Sequence": ("app/domain/sequences/",),
    "Track": ("app/domain/sequences/",),
    "Clip": ("app/domain/sequences/",),
    "SequenceOperation": ("app/domain/sequences/",),
    "SequenceRevision": ("app/domain/sequences/",),
    # 逐字稿
    "Transcript": ("app/domain/transcripts/",),
    "TranscriptSegment": ("app/domain/transcripts/",),
    "TranscriptToken": ("app/domain/transcripts/",),
    "ClipTranscriptRef": ("app/domain/transcripts/", "app/domain/sequences/"),
    # 资源库
    "Voice": ("app/domain/voices/voices.py",),
    "Lut": ("app/domain/luts/",),
    "Font": ("app/domain/fonts/",),
    "GeneratedAsset": ("app/domain/generation/",),
    "GenerationJob": ("app/domain/generation/",),
    "GenerationSession": ("app/domain/generation/",),
    # 任务总线(Job/TaskEvent 只在总线创建;进度/事件请走 jobs.py 的接口)
    "Job": ("app/domain/jobs.py",),
    "TaskEvent": ("app/domain/jobs.py",),
    "Notification": ("app/domain/notifications.py",),
    "ActivityEvent": ("app/domain/collaboration/",),
    "Comment": ("app/domain/collaboration/",),
    "CommentMention": ("app/domain/collaboration/",),
    # 编排
    # 「谁的」与「共享给谁」是同一张表管的,所以它只归 sharing 域写。
    # 部署级开关只归 deployment 域写 —— 「这台后端怎么对外」只该有一处答案。
    "DeploymentConfig": ("app/domain/deployment.py",),
    "ResourceShare": ("app/domain/sharing.py",),
    # 钥匙只归 provider_credentials 域写 —— 「谁的钥匙」这个问题只该有一处答案。
    "ProviderCredential": ("app/domain/providers/credentials.py", "app/domain/providers/auth.py"),
    "ScheduledTask": ("app/domain/scheduler/",),
    "ScheduledTaskRun": ("app/domain/scheduler/",),
    "Workflow": ("app/domain/workflows/",),
    "WorkflowRevision": ("app/domain/workflows/",),
    "WorkflowRevisionAttestation": ("app/domain/workflows/",),
    "Scene3D": ("app/domain/scenes/operations.py",),
    "Scene3DRevision": ("app/domain/scenes/operations.py",),
    "Scene3DModel": ("app/domain/scenes/operations.py",),
    "Board": ("app/domain/boards/",),
    "Note": ("app/domain/notes/",),
    "NoteRevision": ("app/domain/notes/",),
    # 发布
    "PublishAccount": ("app/domain/publish/",),
    "PublishTask": ("app/domain/publish/",),
    # 浏览器自动化(RPA / 智能体)
    "BrowserProfile": ("app/domain/browser/",),
    "BrowserSession": ("app/domain/browser/",),
    "BrowserAction": ("app/domain/browser/",),
    # 配置
    #: 用户自己配的连接在 provider_connections 建;插件实例对应的那条(只是生成领域指向实例的把手,
    #: ADR 0020)在 providers.adopt_plugin_connection 建。
    "ProviderProfile": ("app/domain/providers/connections.py", "app/domain/providers/selection.py"),
    "ProviderDefault": ("app/domain/providers/defaults.py",),
    "ProviderModel": ("app/domain/providers/models.py",),
    #: 自定义参数组跟着连接走(FK + ondelete CASCADE),所以它没有自己的 owner_user_id ——
    #: 连接删了它一起清,不会留下指向虚空的孤儿。
    "GenerationCapabilityProfile": ("app/domain/generation/custom_profiles.py",),
    "GenerationCapabilityDeclaration": ("app/domain/generation/resolution.py",),
    "ProviderPricingRule": ("app/domain/billing/usage.py",),
    "ProviderUsageEvent": ("app/domain/billing/usage.py",),
    "AiRuntimeConfig": ("app/domain/ai_runtime.py",),
    # 单例行由 network 域按需创建(get_config),路由只负责改值。
    "NetworkConfig": ("app/domain/network.py",),
    "TtsConfig": ("app/domain/voices/tts_settings.py",),
    # 智能体/集成
    "AgentSession": ("app/domain/agent/",),
    # 分组对话和生成共用一张表(kind 分开),所以归属在中立的 domain/session_groups。
    "SessionGroup": ("app/domain/session_groups/",),
    "AgentMessage": ("app/domain/agent/",),
    "AgentMemory": ("app/domain/agent/",),
    "AgentQuestion": ("app/domain/agent/",),
    "ToolConfirmation": ("app/domain/agent/",),
    "FeishuBot": ("app/domain/feishu/",),
    "FeishuBinding": ("app/domain/feishu/",),
    "FeishuBindCode": ("app/domain/feishu/",),
    "PluginPackage": ("app/domain/plugins/",),
    "PluginMarketHold": ("app/domain/plugins/",),
    "PluginInstance": ("app/domain/plugins/",),
    "PluginCapability": ("app/domain/plugins/",),
    "AgentVoicePref": ("app/domain/voices/",),
    "PluginPermissionGrant": ("app/domain/plugins/",),
    "PluginCredential": ("app/domain/plugins/",),
    "PluginInvocation": ("app/domain/plugins/",),
    "PluginCapabilityDefault": ("app/domain/plugins/",),
    #: 素材外链的缓存由生成链路写(传完记下、过期重传),见 generation/public_links。
    "PluginPublicLink": ("app/domain/generation/public_links.py",),
    #: 引用表是派生数据:只由 db/references 按各来源的 JSON 写(flush 时跟着写、启动时按版本重建)。
    "RecordReference": ("app/db/references.py",),
    "RecordReferenceIndex": ("app/db/references.py",),
}

#: 不受这条规矩约束的层。
#:
#: **`app/api/routes/` 曾经在这里,而它不该在。** 豁免的理由写的是「路由是薄转译」——
#: 那句话在写下时可能是真的,但整层豁免的后果是:那下面 19 处直接建行**一处都看不见**,
#: 其中 12 处所建的表,声明的拥有方只有领域模块。而 ADR-0003、ARCHITECTURE.md、
#: 以及一次审计的「没有发现问题的地方」三处都把"棘轮强制"当成了既成事实。
#:
#: **一个被普遍相信的保证,和一个没有的保证,不是同一种风险 —— 前者更坏**,因为它让人
#: 不再去看。所以那一层从这里拿掉,存量写进棘轮的 ALLOWLIST:已知债务要是一份**看得见、
#: 会被数**的清单,而不是一个让整层消失的前缀。
#:
#: 留下的两条是真的不受限:`app/db/` 是建表和迁移本身(它不"属于"任何领域),
#: `app/api/schemas/` 只有出入参模型。
EXEMPT_PREFIXES: tuple[str, ...] = ("app/db/", "app/api/schemas/")
