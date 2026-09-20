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
};
