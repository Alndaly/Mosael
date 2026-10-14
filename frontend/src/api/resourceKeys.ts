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
  //: 素材库、单份素材(`["assets", "detail", id]`)、文档阅读器挂在 `asset` 下的那几份、波形;
  //: 还有插件那边**按产出看的两份**:工作流库详情(大卡片上「最近的那一份产出」)和详情里「最近的产出」那一组。
  //: 它们说的是"这张工作流产出过什么",而产出是别处(创作页、工作台、画板、工作流节点、智能体)跑出来的 ——
  //: 不挂在这里的话,别处跑完这边照旧是旧的一组(维护者:工作流详情里的生成历史不会自动同步)。
  assets: ["assets", "asset", "waveform", "workflow-library", "workflow-outputs"],
  sequences: ["sequences"],
  transcripts: ["transcript"],
  //: 工作流列表、编辑器里开着的那张,和它的运行记录;节点包装完之后这张工作流缺什么也跟着变。
  //: 还有**插件连接上那张工作流自己的文件**:库详情里的「表单」「能填什么」「能调什么」「交出什么」「用到的模型」
  //: 全从这一份列表来(`["workflow-library", 连接, 工作区]`)。写它的路不止一条 —— 库里存表单、导入、改名、复制、
  //: 恢复、升级旧格式标记,以及**工作台里 ComfyUI 自己存盘**(桥报的 `modified` 从有到无,见 pluginCaches 的
  //: refreshConnectionCatalog)。少挂这一个键:库详情停在改之前那一份上(维护者:在工作台改完表单回到详情页,
  //: 「表单 1 · 4 项」「能填什么 2」还是旧的),而它 staleTime 30 秒、又不在获焦时重拉。
  workflows: ["workflows", "workflow-runs", "node-installs", "workflow-library"],
  publish_tasks: ["publish-tasks"],
  //: 生成记录和创作会话(ADR 0055);同上,一次生成也是一份产出。
  generations: ["generation-jobs", "generation-sessions", "workflow-library", "workflow-outputs"],
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
  //: 插件那台服务器上的模型文件:模型库、单个模型的详情。
  models: ["model-library", "model-library-detail"],
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
