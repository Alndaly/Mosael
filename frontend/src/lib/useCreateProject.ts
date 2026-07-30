import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api, type Project, type ProjectWithStats } from "@/api/client";
import { useI18n } from "@/app/preferences";

/**
 * 新建项目并跳进它 —— 三个入口(首页、顶栏项目切换器、剪辑页空态)共用一份。
 *
 * 抽出来不只是去重:`onSuccess` 里那步「先写缓存再跳转」是必须的,而它很容易在复制时
 * 被漏掉。App 侧解析当前项目用的是 `find(projectId) ?? list[0]` 兜底,列表还没刷出新
 * id 的那个间隙里,编辑器会悄悄落到第一个(旧)项目上——表现为「新建项目打开却是旧
 * 时间线」。少一处副本就少一处会漏掉它的地方。
 *
 * 命名沿用「项目 N」,N 取当前缓存里的条数;直接读缓存而不要求调用方传列表,
 * 是为了让没有项目列表在手的调用方(切换器、空态)也能直接用。
 */
export function useCreateProject(workspaceId: string, onCreated: (projectId: string) => void) {
  const qc = useQueryClient();
  const t = useI18n();
  const key = ["projects", workspaceId];

  return useMutation({
    mutationFn: () => {
      const existing = qc.getQueryData<ProjectWithStats[]>(key) ?? [];
      return api<Project>("/api/projects", {
        method: "POST",
        body: JSON.stringify({ workspace_id: workspaceId, name: `${t("projectDefault")} ${existing.length + 1}` }),
      });
    },
    onSuccess: (created) => {
      qc.setQueryData<ProjectWithStats[]>(key, (old) => [
        { ...created, asset_count: 0, sequence_count: 0, timeline_duration: 0 },
        ...(old ?? []),
      ]);
      void qc.invalidateQueries({ queryKey: key });
      onCreated(created.id);
    },
  });
}
