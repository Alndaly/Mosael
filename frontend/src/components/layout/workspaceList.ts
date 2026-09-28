import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, deleteWorkspace, type Workspace } from "@/api/client";
import { useI18n } from "@/app/preferences";

/** 工作区列表这一份查询。WorkspaceGate、切换器、设置页读的是同一个缓存,所以 key 和取法只写这一次。 */
export const WORKSPACES_QUERY = {
  queryKey: ["workspaces"] as const,
  queryFn: () => api<Workspace[]>("/api/workspaces"),
};

/**
 * 删除工作区,连同删完之后的收尾 —— 切换器和设置页共用这一份。
 *
 * 此前设置页自己写了一个只 invalidate 的版本:删的正是当前工作区时,列表重新取回来之前,
 * 界面还挂在一个已经不存在的工作区上,各页的查询接着拿那个 id 去打请求。
 *
 * 收尾的顺序:删的是当前这个 → 先把选择挪到列表里第一个不是它的 → 再从缓存里拿掉它、让列表失效。
 * 反过来的话,中间那一瞬列表里没有当前工作区,WorkspaceGate 会先弹一次。
 * 没给 `onSelectWorkspace` 的入口(设置页拿不到它)只做后半截:缓存里拿掉之后,WorkspaceGate 的
 * 兜底(找不到 → 列表第一个)落到的正是同一个「第一个不是它的」。
 */
export function useDeleteWorkspace({
  currentWorkspaceId,
  onSelectWorkspace,
  onSettled,
}: {
  currentWorkspaceId?: string;
  onSelectWorkspace?: (id: string) => void;
  onSettled?: () => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteWorkspace(id),
    onSuccess: (_data, id) => {
      if (id === currentWorkspaceId) {
        const next = qc.getQueryData<Workspace[]>(WORKSPACES_QUERY.queryKey)?.find((ws) => ws.id !== id);
        if (next) onSelectWorkspace?.(next.id);
      }
      qc.setQueryData<Workspace[]>(WORKSPACES_QUERY.queryKey, (old) => old?.filter((ws) => ws.id !== id));
      void qc.invalidateQueries({ queryKey: WORKSPACES_QUERY.queryKey });
      toast.success(t("workspaceDeleted"));
    },
    onError: (error: Error) => toast.error(error.message),
    // 删完(成没成)再关确认框 —— 进行中它一直开着、确认键转圈。
    onSettled,
  });
}
