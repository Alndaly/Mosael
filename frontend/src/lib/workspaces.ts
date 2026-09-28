import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { createWorkspace, deleteWorkspace, listWorkspaces, renameWorkspace, type Workspace } from "@/api/client";
import { workspaceKeys } from "@/api/queryKeys";
import { useI18n } from "@/app/preferences";

/**
 * 工作区列表的读和写。
 *
 * 读它的有 WorkspaceGate(App)、切换器(AppShell)、设置 → 团队与成员;写它的是这里的新建、
 * 改名、删除。它们放在 lib/ 而不是某个组件旁边,是因为这几个调用方分属 app、components、
 * features 三层 —— 和 `useCreateProject` 同理:谁都能用,谁都不拥有它。
 *
 * 当前是哪个工作区**不在这里**:那是 WorkspaceGate 一个 state,解析规则是
 * `find(activeId) ?? list[0]`。这里的写操作只管把缓存里的列表改对,选择会跟着那条规则走。
 */
export function useWorkspaces() {
  return useQuery({ queryKey: workspaceKeys.all(), queryFn: listWorkspaces });
}

/**
 * 新建工作区。首次启动的「创建工作区」和切换器里的「新建」共用这一份;建好之后选中它由调用方做。
 *
 * 先把新的那个塞进缓存,再交给 `onCreated`:调用方接着就会选中它,而那一刻列表里要是还没有它,
 * WorkspaceGate 的兜底(找不到 → 退回 list[0])会把选择弹回原来那个。
 */
export function useCreateWorkspace({
  onCreated,
  onSettled,
}: {
  onCreated: (created: Workspace) => void;
  onSettled?: () => void;
}) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => createWorkspace(name),
    onSuccess: (created) => {
      qc.setQueryData<Workspace[]>(workspaceKeys.all(), (old) => (old ? [created, ...old] : [created]));
      void qc.invalidateQueries({ queryKey: workspaceKeys.all() });
      onCreated(created);
    },
    onSettled,
  });
}

/** 改名。切换器的右键菜单和设置页的按钮共用这一份。 */
export function useRenameWorkspace({ onSettled }: { onSettled?: () => void } = {}) {
  const t = useI18n();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => renameWorkspace(id, name),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: workspaceKeys.all() });
      toast.success(t("saved"));
    },
    onError: (error: Error) => toast.error(error.message),
    onSettled,
  });
}

/**
 * 删除工作区。切换器和设置页共用这一份。
 *
 * 删的若正是当前工作区,这里**不去挑下一个**:从缓存里拿掉它之后,WorkspaceGate 的
 * `find(activeId) ?? list[0]` 落到的就是剩下的第一个,并把它写回本地存储。先改缓存再失效,
 * 是为了不等那次重新请求 —— 否则这段时间里各页还拿着一个已经不存在的工作区 id 去打请求。
 */
export function useDeleteWorkspace({ onSettled }: { onSettled?: () => void } = {}) {
  const t = useI18n();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteWorkspace(id),
    onSuccess: (_data, id) => {
      qc.setQueryData<Workspace[]>(workspaceKeys.all(), (old) => old?.filter((ws) => ws.id !== id));
      void qc.invalidateQueries({ queryKey: workspaceKeys.all() });
      toast.success(t("workspaceDeleted"));
    },
    onError: (error: Error) => toast.error(error.message),
    // 删完(成没成)再关确认框 —— 进行中它一直开着、确认键转圈。
    onSettled,
  });
}
