import type { QueryClient } from "@tanstack/react-query";

import type { components } from "@/api/generated/schema";

/**
 * 后端说「改了哪种数据」,这里说「那是哪些缓存」(ADR 0053)。
 *
 * 一次操作改了什么由做这件事的那一方声明:任务做完按目录里的 `affects`(components/jobs/jobKinds),需要确认的工具批完
 * 按卡上的 `writes`(features/agent/confirmationCaches)。两边用的是同一套词(backend/app/domain/resources.py),
 * 换成缓存键的只有这一张表 —— 此前确认卡那一侧是一份按工具逐行手写的清单,漏过项目、发布任务。
 *
 * 值是缓存键的**第一段**:按前缀失效,一个工作区、一篇笔记、一张板的细分都在它下面。多刷一次的代价是一个本地请求,
 * 少刷一次的代价是人看着旧数据以为没做成(见 queryKeys 开头那段)。
 *
 * 类型是从后端的词表生成的(api/generated/schema):后端加一个词、这里没给键,类型检查就过不去;resourceKeys.test.ts
 * 再守着「每个键都真有查询在用」。
 */
export type Resource = components["schemas"]["ConfirmationOut"]["writes"][number];

export const RESOURCE_QUERY_KEYS: Record<Resource, readonly string[]> = {
  //: 素材库、单份素材(`["assets", "detail", id]`)、文档阅读器挂在 `asset` 下的那几份、波形。
  assets: ["assets", "asset", "waveform"],
  sequences: ["sequences"],
  transcripts: ["transcript"],
  //: 工作流列表、编辑器里开着的那张,和它的运行记录。
  workflows: ["workflows", "workflow-runs"],
  publish_tasks: ["publish-tasks"],
  //: 生成记录和创作会话(ADR 0055)。
  generations: ["generation-jobs", "generation-sessions"],
  //: 画板列表和开着的那张板的详情(BoardsView 按版本号合进本地,见 queryKeys 的 boardKeys)。
  boards: ["boards"],
  //: 资产库:参考图挂上了新的(资产格的能力、详情页的「补全多角度」「生成表情」)。
  entities: ["entities"],
  //: 配音库:一把嗓子复刻到了百炼(每一行显示它在哪儿能念)。
  voices: ["voices"],
  //: 外壳的项目切换器、剪辑页的当前项目、首页。
  projects: ["projects"],
  //: 笔记列表一族,和正在编辑的那一篇(编辑器按最小差异接过来,见 notes/noteSelection.followMarkdown)。
  notes: ["notes", "note"],
  //: 设置页的技能列表、「/」菜单、开着的编辑表单(ADR 0040)。
  skills: ["agent-skills"],
};

/** 这几种数据对应的缓存键(第一段),去重。认不出的词跳过 —— 新前端遇上更老的后端时不该炸。 */
export function queryKeysFor(resources: Iterable<string>): string[] {
  const keys = new Set<string>();
  for (const resource of resources) {
    for (const key of RESOURCE_QUERY_KEYS[resource as Resource] ?? []) keys.add(key);
  }
  return [...keys];
}

/** 把这几种数据的缓存一起作废。 */
export function invalidateResources(qc: QueryClient, resources: Iterable<string>): void {
  for (const key of queryKeysFor(resources)) void qc.invalidateQueries({ queryKey: [key] });
}
