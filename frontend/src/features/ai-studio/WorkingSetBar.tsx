import { FolderOpen } from "lucide-react";

import type { ProjectWithStats } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { isViewOnly, useSessionSettings } from "@/features/agent/currentAgentSession";
import { STUDIO_PLACE } from "@/features/agent/places";
import type { components } from "@/api/generated/schema";

type AgentSession = components["schemas"]["AgentSessionOut"];
type AgentWorkingSet = components["schemas"]["AgentWorkingSet"];

const NONE = "__none";

/**
 * 会话自己的工作上下文。
 *
 * **不跟壳层的全局 projectId 走**:AI Studio 可以对着 A 项目聊,而编辑器里开着 B 项目;
 * 这里选中的值只属于这段会话。草稿上也能选,第一句话建会话时一起带上。
 */
export function WorkingSetBar({
  workspaceId,
  session,
  projects,
}: {
  workspaceId: string;
  session: AgentSession | null;
  projects: ProjectWithStats[];
}) {
  const t = useI18n();
  const { settings, update } = useSessionSettings(workspaceId, STUDIO_PLACE, session);
  const workingSet: AgentWorkingSet = settings.working_set ?? { project_id: "", surface: "ai" };
  const projectId = workingSet.project_id || "";
  const value = projectId || NONE;
  const known = projects.some((project) => project.id === projectId);

  return (
    <div className="flex min-w-0 items-center gap-1.5 text-ui-sm text-muted-foreground">
      <FolderOpen size={14} className="shrink-0 opacity-70" aria-hidden />
      <Select
        key={`${value}:${known}`}
        value={value}
        onValueChange={(next) =>
          update.mutate({
            working_set: { project_id: next === NONE ? "" : next, surface: "ai" },
          })
        }
        disabled={isViewOnly(session) || update.isPending}
      >
        <SelectTrigger
          size="sm"
          className="w-44 min-w-0 border-0 bg-transparent shadow-none"
          aria-label={t("agentWorkingProject")}
        >
          <SelectValue placeholder={t("agentWorkingNone")} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NONE}>{t("agentWorkingNone")}</SelectItem>
          {projectId && !known && <SelectItem value={projectId}>{t("agentWorkingDeletedProject")}</SelectItem>}
          {projects.map((project) => (
            <SelectItem key={project.id} value={project.id}>
              {project.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {/* 面板本身在阶段 2 只可能是 AI Studio;阶段 3 的 surface host 会替换这一句。 */}
      <span className="hidden shrink-0 text-ui-xs text-muted-foreground lg:inline">{t("navAi")}</span>
    </div>
  );
}
