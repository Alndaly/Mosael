import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api, type Project, type ProjectWithStats } from "@/api/client";
import { useI18n } from "@/app/preferences";

/**
 * 下一个不重名的默认名字:`未命名项目`、`未命名项目 2`、`未命名项目 3`…
 *
 * **序号不能取"现有几个"。** 那样删掉一个再新建就会撞名 —— 建三个删掉第二个,下一个又叫
 * 「项目 3」,和还在的那个同名。这里按**已经占用的名字**找空位,所以删掉「未命名项目 2」
 * 之后,下一个正好补回那个空位。
 *
 * 第一个不带序号:一个工作区里只有一个项目时,「未命名项目 1」里的那个 1 什么也没说明。
 */
export function nextProjectName(stem: string, existing: { name: string }[]): string {
  const taken = new Set(existing.map((project) => project.name));
  if (!taken.has(stem)) return stem;
  for (let index = 2; ; index += 1) {
    const candidate = `${stem} ${index}`;
    if (!taken.has(candidate)) return candidate;
  }
}

/**
 * 新建项目并跳进它 —— 三个入口(首页、顶栏项目切换器、剪辑页空态)共用一份。
 *
 * 抽出来不只是去重:`onSuccess` 里那步「先写缓存再跳转」是必须的,而它很容易在复制时
 * 被漏掉。App 侧解析当前项目用的是 `find(projectId) ?? list[0]` 兜底,列表还没刷出新
 * id 的那个间隙里,编辑器会悄悄落到第一个(旧)项目上——表现为「新建项目打开却是旧
 * 时间线」。少一处副本就少一处会漏掉它的地方。
 *
 * 直接读缓存而不要求调用方传列表,是为了让没有项目列表在手的调用方(切换器、空态)
 * 也能直接用。
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
        body: JSON.stringify({ workspace_id: workspaceId, name: nextProjectName(t("projectDefault"), existing) }),
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
