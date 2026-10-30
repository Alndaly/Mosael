/**
 * 更新用户信息之后**必须**刷新的缓存清单。每一条都要有对应的 `invalidateQueries`,
 * 漏一条就是「改了没生效」:
 *
 * ```
 * 改昵称/短名/头像  -> viewer(站头首字母、色块、aria-label) + 我的分享里的作者名 + 个人页
 * 上传/删除分享     -> 我的分享 + 概览统计 + 该 kind 的列表(community/plugins/workflows)
 * 点赞/收藏/下载    -> 列表分组(卡片上的统计) + 我的分享
 * 评论新增/删除     -> 同上 + 通知(作者会收到一条,未读角标也要变)
 * 标已读            -> unread + 通知列表
 * ```
 *
 * 个人页展示的就是 viewer 那一份 `/me`(见 `queryKeys.profile`),所以刷 viewer 同时
 * 覆盖个人页;公开列表卡片上的作者名也来自同一份 user,改资料时一并刷掉。
 *
 * 这里只依赖一个极小的 `invalidateQueries` 接口,而不是 QueryClient 的具体类型 ——
 * node 测试可以传一个只记录调用的桩,断言「真的收到了 viewer 键」。
 */
import { queryKeys, type ShareListKind } from "./queryKeys";

export type QueryKey = readonly unknown[];

/** QueryClient 只需要这一个方法;接口窄一点,测试和组件都能传自己手里的那个。 */
export type InvalidationClient = {
  invalidateQueries: (filters: { queryKey: QueryKey }) => Promise<unknown> | unknown;
  /** 退出登录时管理台要**删掉**而不是标脏,避免下一个人从缓存里看到上一个管理员的账号。 */
  removeQueries?: (filters: { queryKey: QueryKey }) => unknown;
};

type ShareKind = ShareListKind | "board";

async function invalidate(client: InvalidationClient, keys: readonly QueryKey[]): Promise<void> {
  await Promise.all(keys.map((queryKey) => client.invalidateQueries({ queryKey })));
}

/** 登录 / 注册成功:站头必须重新问一次「我是谁」,未读角标也要按新账号来。 */
export function invalidateAfterAuth(client: InvalidationClient): Promise<void> {
  return invalidate(client, [queryKeys.viewer(), queryKeys.unread()]);
}

/** 密码设置 / 修改只改 viewer 里的 `has_password`。 */
export async function invalidateAfterPasswordChange(client: InvalidationClient): Promise<void> {
  return invalidate(client, [queryKeys.viewer()]);
}

/**
 * 退出登录。**最不能省的一条**:不清 viewer 的话,站头还挂着上一个账号的头像,
 * 用户会以为根本没退出去;未读角标 / 通知列表 / 我的分享也都是上一个账号的。
 */
export async function invalidateAfterSignOut(client: InvalidationClient): Promise<void> {
  await invalidate(client, [
    queryKeys.viewer(),
    queryKeys.unread(),
    queryKeys.notifications(),
    queryKeys.sharesByMe(),
  ]);
  // 管理台缓存里有账号、订单和审计;**退出时直接移除**。
  client.removeQueries?.({ queryKey: queryKeys.admin() });
}

/**
 * 改昵称 / 短名 / 头像(个人信息页、第一次发分享前的 IdentityForm):
 * viewer 用于站头首字母 / 色块 / aria-label,sharesByMe 用于「我的分享」与概览,
 * shareList 用于公开列表卡片上的作者名。
 */
export function invalidateAfterProfileSave(client: InvalidationClient): Promise<void> {
  return invalidate(client, [queryKeys.viewer(), queryKeys.sharesByMe(), queryKeys.shareList()]);
}

/**
 * 上传 / 删除分享:我的分享 + 概览统计(两者都从 sharesByMe 求和),
 * 以及该 kind 的列表(community / plugins / workflows 里混着用户分享)。
 * `board` 没有独立列表页,退回刷新全部列表。
 */
export function invalidateAfterShareChange(client: InvalidationClient, kind?: ShareKind): Promise<void> {
  const listKey = kind === "plugin" || kind === "workflow" ? queryKeys.shareList(kind) : queryKeys.shareList();
  return invalidate(client, [queryKeys.sharesByMe(), listKey]);
}

/**
 * 详情页上的一次互动。列表卡片上的四项统计都来自 `shareList` 的那份 `CloudShare`,
 * 「我的分享」/ 概览也各有一份 —— 只改详情页本地 state 的话,回到列表还是旧数字。
 *
 * **只标脏,不写数据**:不要把列表 `setQueryData` 成空数组(那是「整个列表没了」,
 * 不是「这条的统计变了」);重取会拿到云端真实的数。
 *
 * 评论还会让作者收到通知(未读角标随之变化),所以额外刷通知的整组前缀;
 * 点赞 / 收藏 / 下载不会产生通知。
 */
export type ShareInteractionKind = "like" | "favorite" | "download" | "comment";

export function invalidateAfterShareInteract(
  client: InvalidationClient,
  kind: ShareInteractionKind,
): Promise<void> {
  const keys: QueryKey[] = [queryKeys.shareList(), queryKeys.sharesByMe()];
  if (kind === "comment") keys.push(queryKeys.notificationsAll());
  return invalidate(client, keys);
}

/** 标已读(单条或全部):站头角标 + 通知列表。 */
export function invalidateAfterMarkRead(client: InvalidationClient): Promise<void> {
  return invalidate(client, [queryKeys.unread(), queryKeys.notifications()]);
}
