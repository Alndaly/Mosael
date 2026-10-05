import type { components } from "@/api/generated/schema";
import { api } from "@/api/transport";

/**
 * 智能体技能(ADR 0040):工作区的 SKILL.md 文件夹。`ref` 是模型看到的名字 —— 内置和工作区的就是 `name`,
 * 插件的写成 `插件 id:名字` —— 界面也拿它当标识。
 */
export type AgentSkill = components["schemas"]["AgentSkillOut"];

const skillsPath = (workspaceId: string) => `/api/workspaces/${encodeURIComponent(workspaceId)}/skills`;

export const listSkills = (workspaceId: string) => api<AgentSkill[]>(skillsPath(workspaceId));
