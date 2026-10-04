import { useQuery } from "@tanstack/react-query";

import { listBrowserProfiles, type BrowserProfile } from "@/api/client";

/**
 * 前台视图对应的浏览器池档案:**按分区认**。视图 id 对池档案是分区名、对发布账号是账号 id、对 RPA 会话是
 * 会话 id —— 三种东西,只有分区是档案上记着的同一个值。认不出(RPA 的临时会话)就是没有档案。
 */
export function profileForPartition(
  profiles: readonly BrowserProfile[] | undefined,
  partition: string | null | undefined,
): BrowserProfile | null {
  if (!partition) return null;
  return profiles?.find((profile) => profile.partition === partition) ?? null;
}

/**
 * 当前视图对应的档案 id。要借登录态的动作(下载、开工)**等清单到了再定**:清单还没回来时按「没有档案」发出去,
 * 下载会悄悄按公开内容下、模板会用一个没登录的具名会话 —— 而用户正看着的是登录后的那一页。
 */
export function useViewProfile(workspaceId: string, partition: string | null | undefined): () => Promise<string | null> {
  const profiles = useQuery({
    queryKey: ["browser-profiles", workspaceId],
    queryFn: () => listBrowserProfiles(workspaceId),
    staleTime: 30_000,
  });
  return async () => {
    const list = profiles.data ?? (await profiles.refetch()).data;
    return profileForPartition(list, partition)?.id ?? null;
  };
}
