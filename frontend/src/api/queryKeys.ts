/**
 * 缓存的键**在一处定义**,取数和失效各有各的写法。
 *
 * 为什么要有这一份:React Query 按**前缀**匹配失效,所以同一份数据用几种形状的键并存时,
 * 对不对全看谁比谁长 —— 而那是每个调用点各自记着的事。素材这一族就这么错了:
 *
 *     剪辑页取数   ["assets", 工作区, 项目]      ← 三段
 *     首页/音频取数 ["assets", 工作区]           ← 两段
 *     剪辑页失效   ["assets", 工作区, 项目]      ← 三段:**匹配不到两段那些**
 *
 * 于是在剪辑页里导入一段素材,首页的素材列表和 AI 工作台的音频列表不会刷新,停在旧数据上,
 * 直到下次重新挂载。有一处已经被手动补成「两个键都失效一遍」(EditorView 里那对相邻的
 * invalidateQueries),那正是踩过一次、只补了一处的痕迹。
 *
 * 所以这里把两件事分开说:
 *
 *   `assetKeys.list(...)`  取数用 —— 想要多细就多细;
 *   `assetKeys.all(ws)`    失效用 —— 永远是最短的那个前缀,匹配到这个工作区下的每一份素材缓存。
 *
 * 失效**一律用 `.all()`**:多刷一次的代价是一个本地请求,少刷一次的代价是用户看着旧数据
 * 以为自己没导入成功。
 */

/** 素材:按工作区,可选按项目细分。 */
export const assetKeys = {
  /** 失效用:这个工作区下的所有素材缓存(含按项目细分的那些)。 */
  all: (workspaceId: string) => ["assets", workspaceId] as const,
  /** 取数用:整个工作区,或某个项目里的那些。 */
  list: (workspaceId: string, projectId?: string | null) =>
    (projectId ? (["assets", workspaceId, projectId] as const) : (["assets", workspaceId] as const)),
  /** 失效用:所有工作区 —— 只在不知道自己动了哪个工作区时用(智能体的确认卡就是这种)。 */
  everywhere: () => ["assets"] as const,
  /**
   * 取数用:按 id 取的单份素材。只有 id 的地方(工具结果、工作流节点、笔记来源)拿不到工作区,
   * 所以它挂在 `everywhere()` 下面 —— 改名、改标签、删除都按 `everywhere()` 失效,匹配得到它。
   * 此前这份数据散在 `asset` / `agent-asset` / `note-source` 三个键族里,哪个都不会被失效。
   */
  detail: (assetId: string) => ["assets", "detail", assetId] as const,
};

/**
 * 工作区列表:用户级,不分工作区,只有这一种形状 —— 取数、写缓存、失效都用它。
 * 读写它的几处(WorkspaceGate、切换器、设置页、通知中心接受邀请)都经 `lib/workspaces`。
 */
export const workspaceKeys = {
  all: () => ["workspaces"] as const,
};

/** 音色库(克隆出来的那些声音):按工作区,只有这一种形状。 */
export const voiceKeys = {
  all: (workspaceId: string) => ["voices", workspaceId] as const,
};

/**
 * 模型服务商这一族(见 `api/domains/providers`)。连接、模型行、能力默认、能力候选这几份
 * 互相牵连 —— 改了连接或模型,默认模型那几格和生成选择器都要跟着变 —— 所以失效它们的那份清单
 * (`features/settings/providerCaches`、`features/plugins/pluginCaches`)也从这里取前缀。
 */
export const providerKeys = {
  profiles: () => ["provider-profiles"] as const,
  vendors: () => ["provider-vendors"] as const,
  /** 不带参数是失效用的前缀;带连接 id 是那一条连接的模型行。 */
  models: (profileId?: string) => (profileId ? (["provider-models", profileId] as const) : (["provider-models"] as const)),
  defaults: () => ["provider-defaults"] as const,
  /** 不带参数是失效用的前缀;带能力是那一项能力的候选,再带执行通道(`surface`)是那条通道上的。 */
  capabilityModels: (capability?: string, surface?: string) =>
    (capability
      ? surface
        ? (["capability-models", capability, surface] as const)
        : (["capability-models", capability] as const)
      : (["capability-models"] as const)),
  health: (profileId: string) => ["provider-health", profileId] as const,
  quota: (profileId: string) => ["provider-quota", profileId] as const,
  /** 登录还没发起时 loginId 是 null(那时查询本就不开)。 */
  oauthLogin: (profileId: string, loginId: string | null) => ["provider-oauth-login", profileId, loginId] as const,
  generationProfiles: (profileId: string, kind: string) => ["generation-profiles", profileId, kind] as const,
  pricingRules: (workspaceId: string) => ["provider-pricing-rules", workspaceId] as const,
};

/**
 * 确认卡(见 `api/domains/confirmations`)。取数按状态、按会话细分;批准 / 拒绝之后失效用
 * `.all(ws)` —— 待批的那几份和「自动放行留痕」那一栏都在它下面。
 */
export const confirmationKeys = {
  all: (workspaceId: string) => ["confirmations", workspaceId] as const,
  /** 带会话 id 是那次对话的卡;不带是整个工作区的(全局确认中心兜底用)。 */
  pending: (workspaceId: string, sessionId?: string) =>
    (sessionId
      ? (["confirmations", workspaceId, "pending", sessionId] as const)
      : (["confirmations", workspaceId, "pending"] as const)),
  approved: (workspaceId: string, sessionId: string) => ["confirmations", workspaceId, "approved", sessionId] as const,
};

/**
 * 素材的转写。逐字稿面板、字幕生成、按说话人建音色读的是同一份,所以取法也只有一种
 * (`api/domains/assets.getAssetTranscript`:没转写过是 null,不是错误)。此前同一个键下挂着
 * 两种取法 —— 一处 404 存 null、一处 404 抛错 —— 两个组件同时挂着时缓存里是哪一种看谁先发请求。
 */
export const transcriptKeys = {
  all: () => ["transcript"] as const,
  of: (assetId: string) => ["transcript", assetId] as const,
};

/**
 * 笔记。列表、主题、搜索选择器、附件选择器、引用卡都挂在 `lists(ws)` 下 —— 保存、删除、恢复之后
 * 失效它一次就全部覆盖。此前同一份「按关键词列笔记」在 `note-picker` 与 `note-attach` 两个键族里,
 * 只有一处会被失效,另一处在挂着的时候看的是旧的。
 *
 * **正在编辑的那一篇(`detail`)故意不在这个前缀下**:编辑器手里有草稿,列表一刷新不该把开着的
 * 那篇也重取一遍;它由编辑器保存时自己 `setQueryData`。
 */
export const noteKeys = {
  /** 失效用:所有工作区的笔记列表 —— 只在不知道动了哪个工作区时用(画板、素材页把东西存成笔记)。 */
  everywhere: () => ["notes"] as const,
  lists: (workspaceId: string) => ["notes", workspaceId] as const,
  page: (workspaceId: string, search: string, filter: unknown) => ["notes", workspaceId, "page", search, filter] as const,
  topics: (workspaceId: string, trashed: boolean) => ["notes", workspaceId, "topics", trashed] as const,
  search: (workspaceId: string, q: string) => ["notes", workspaceId, "search", q] as const,
  reference: (workspaceId: string, noteId: string, revision?: number) =>
    ["notes", workspaceId, "reference", noteId, revision] as const,
  detail: (workspaceId: string, noteId: string) => ["note", workspaceId, noteId] as const,
  /** 不带修订号是失效用的前缀。 */
  history: (noteId: string, revision?: number) =>
    (revision === undefined ? (["note-history", noteId] as const) : (["note-history", noteId, revision] as const)),
  sourceMessage: (workspaceId: string, messageId: string) => ["note-source", workspaceId, "message", messageId] as const,
};
