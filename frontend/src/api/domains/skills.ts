import type { components } from "@/api/generated/schema";
import { api, apiBlob } from "@/api/transport";

/**
 * 智能体技能(ADR 0040):工作区的 SKILL.md 文件夹。`ref` 是模型看到的名字 —— 内置和工作区的就是 `name`,
 * 插件的写成 `插件 id:名字` —— 界面也拿它当标识。
 */
export type AgentSkill = components["schemas"]["AgentSkillOut"];
export type AgentSkillDetail = components["schemas"]["AgentSkillDetailOut"];
export type AgentSkillFile = components["schemas"]["AgentSkillFileOut"];
export type AgentSkillWrite = components["schemas"]["AgentSkillWrite"];
export type AgentSkillImport = components["schemas"]["AgentSkillImportOut"];
export type AgentSkillImportItem = components["schemas"]["AgentSkillImportItem"];
export type AgentSkillImportChoice = components["schemas"]["AgentSkillImportChoice"];
export type AgentSkillDraft = components["schemas"]["AgentSkillDraftOut"];

const skillsPath = (workspaceId: string) => `/api/workspaces/${encodeURIComponent(workspaceId)}/skills`;
const skillPath = (workspaceId: string, ref: string) => `${skillsPath(workspaceId)}/${encodeURIComponent(ref)}`;
/** 技能里文件的路径按段编码:`/` 是层级,不能编成 %2F。 */
const filePath = (workspaceId: string, ref: string, path: string) =>
  `${skillPath(workspaceId, ref)}/files/${path.split("/").map(encodeURIComponent).join("/")}`;

export const listSkills = (workspaceId: string) => api<AgentSkill[]>(skillsPath(workspaceId));
export const getSkill = (workspaceId: string, ref: string) => api<AgentSkillDetail>(skillPath(workspaceId, ref));

export const createSkill = (workspaceId: string, body: AgentSkillWrite) =>
  api<AgentSkillDetail>(skillsPath(workspaceId), { method: "POST", body: JSON.stringify(body) });

export const updateSkill = (workspaceId: string, ref: string, body: AgentSkillWrite) =>
  api<AgentSkillDetail>(skillPath(workspaceId, ref), { method: "PUT", body: JSON.stringify(body) });

export const deleteSkill = (workspaceId: string, ref: string) =>
  api<void>(skillPath(workspaceId, ref), { method: "DELETE" });

export const setSkillEnabled = (workspaceId: string, ref: string, enabled: boolean) =>
  api<AgentSkill>(`${skillPath(workspaceId, ref)}/enabled`, { method: "PUT", body: JSON.stringify({ enabled }) });

/** 内置 / 插件的技能复制一份成「我的」,换个名字就能改。 */
export const copySkill = (workspaceId: string, ref: string, name: string) =>
  api<AgentSkillDetail>(`${skillPath(workspaceId, ref)}/copy`, { method: "POST", body: JSON.stringify({ name }) });

/** 导出成 `.zip`(一层同名文件夹)。 */
export const exportSkill = (workspaceId: string, ref: string) => apiBlob(`${skillPath(workspaceId, ref)}/export`);

export function putSkillFile(workspaceId: string, ref: string, path: string, file: Blob): Promise<AgentSkillDetail> {
  const form = new FormData();
  form.set("file", file, path.split("/").pop() || "file");
  return api<AgentSkillDetail>(filePath(workspaceId, ref, path), { method: "PUT", body: form });
}

export const deleteSkillFile = (workspaceId: string, ref: string, path: string) =>
  api<AgentSkillDetail>(filePath(workspaceId, ref, path), { method: "DELETE" });

/** 导入第一步:一个 `.zip`。回全文给人审阅,什么都还没装。 */
export function stageSkillArchive(workspaceId: string, archive: File): Promise<AgentSkillImport> {
  const form = new FormData();
  form.set("archive", archive, archive.name);
  form.set("source_name", archive.name);
  return api<AgentSkillImport>(`/api/workspaces/${encodeURIComponent(workspaceId)}/skill-imports`, { method: "POST", body: form });
}

/**
 * 导入第一步:用户选的一个文件夹(`<input webkitdirectory>`)。文件和它们的相对路径**同序**放进两列 ——
 * 不靠文件名带路径:有的 multipart 解析会把文件名里的目录去掉。
 */
export function stageSkillFolder(workspaceId: string, files: readonly File[]): Promise<AgentSkillImport> {
  const form = new FormData();
  for (const file of files) {
    form.append("files", file, file.name);
    form.append("paths", (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name);
  }
  const first = (files[0] as (File & { webkitRelativePath?: string }) | undefined)?.webkitRelativePath ?? "";
  form.set("source_name", first.split("/")[0] || "");
  return api<AgentSkillImport>(`/api/workspaces/${encodeURIComponent(workspaceId)}/skill-imports`, { method: "POST", body: form });
}

/** 暂存着的一次导入的全文:智能体从链接导入(import_skill)的确认卡照它画审阅,和设置页导入同一份。 */
export const getSkillImport = (workspaceId: string, importId: string) =>
  api<AgentSkillImport>(`/api/workspaces/${encodeURIComponent(workspaceId)}/skill-imports/${encodeURIComponent(importId)}`);

/** 导入第二步:照审阅时的选择落地。 */
export const commitSkillImport = (workspaceId: string, importId: string, choices: AgentSkillImportChoice[]) =>
  api<AgentSkill[]>(`/api/workspaces/${encodeURIComponent(workspaceId)}/skill-imports/${encodeURIComponent(importId)}`, {
    method: "POST",
    body: JSON.stringify({ choices }),
  });

/** 「存成技能」:用这次对话的模型起草一份,不保存。 */
export const draftSkillFromSession = (sessionId: string) =>
  api<AgentSkillDraft>(`/api/agent/sessions/${encodeURIComponent(sessionId)}/skill-draft`, { method: "POST" });
