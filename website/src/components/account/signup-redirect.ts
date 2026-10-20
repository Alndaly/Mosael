/**
 * 注册成功之后去哪儿:**社区页**。
 *
 * 站点自己的信息结构里没有 `/community` 这一页 —— 站头「社区」指向 `/plugins`,
 * 插件与工作流是同一个社区的两个分区(见 `components/community/community-header.tsx`)。
 * 所以目标就是 `/${locale}/plugins`,并且**只写在这一处**:哪天社区真有了独立入口,
 * 改这一行常量即可,别让组件和测试各抄一份路径。
 *
 * 路径带 `[locale]` 段:跳转要落在用户当前语言下,不能硬编码某种语言。
 *
 * 走 `router.push` 是**同源客户端导航** —— 不重建文档、不发新的整页请求;注册本身不建立
 * 会话(成功文案就是让用户去登录),所以这里也没有任何需要清理的浏览器状态。
 */

export const COMMUNITY_PATH = "/plugins";

/**
 * 成功态至少留这么久再跳。
 *
 * 立刻跳的话「账号已创建」等于没出现过,用户不确定账号到底建成没有;要把这句提示带到
 * 社区页得改社区页(另一笔),所以先把成功卡片留在屏幕上 1.5 秒。
 */
export const SIGNUP_REDIRECT_DELAY_MS = 1500;

/** 只依赖 `push`,方便测试塞一个假 router。 */
export type SignupRedirectRouter = { push(href: string): void };

/** 当前语言下的社区页地址。 */
export function communityHref(locale: string): string {
  return `/${locale}${COMMUNITY_PATH}`;
}

/**
 * 安排一次跳转,返回取消函数(直接给 effect 的 cleanup 用)。
 *
 * 取消很重要:用户在这 1.5 秒里自己点了别处、或组件被卸载,定时器不该再把人拽走。
 */
export function scheduleCommunityRedirect(
  router: SignupRedirectRouter,
  locale: string,
  delayMs: number = SIGNUP_REDIRECT_DELAY_MS,
): () => void {
  const timer: ReturnType<typeof setTimeout> = setTimeout(() => router.push(communityHref(locale)), delayMs);
  return () => clearTimeout(timer);
}
