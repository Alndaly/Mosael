import type { WorkflowFile } from "@/api/client";

/**
 * 工作流库列表那一页「看哪些、按什么顺序」的纯函数:子目录怎么排、哪些算「缺东西」、筛和排。界面(WorkflowLibrary)只管摆。
 */

/** 左栏的「全部」和「缺节点或模型」。子目录名不会长这样。 */
export const ALL_WORKFLOWS = "__all__";
export const PROBLEMS_VIEW = "__problems__";
export const TRASH_VIEW = "__trash__";

export const WORKFLOW_KINDS = ["all", "image", "video", "audio", "broken"] as const;
export type WorkflowKindFilter = (typeof WORKFLOW_KINDS)[number];

export const WORKFLOW_SORTS = ["name", "modified", "nodes"] as const;
export type WorkflowSort = (typeof WORKFLOW_SORTS)[number];

/** 缺节点或缺模型(跑不起来、或跑起来要先补东西)。 */
export const lacksSomething = (flow: WorkflowFile) => (flow.missing_nodes?.length ?? 0) > 0 || (flow.missing_models?.length ?? 0) > 0;

/** 左栏的子目录:有工作流的才列,多的在前;一样多按名字。 */
export function workflowFolders(workflows: readonly WorkflowFile[]): { name: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const flow of workflows) if (flow.folder) counts.set(flow.folder, (counts.get(flow.folder) ?? 0) + 1);
  return [...counts.entries()]
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
}

export function inView(workflows: readonly WorkflowFile[], view: string): WorkflowFile[] {
  if (view === ALL_WORKFLOWS) return [...workflows];
  if (view === PROBLEMS_VIEW) return workflows.filter(lacksSomething);
  return workflows.filter((flow) => flow.folder === view);
}

/** 按种类(转不过来的单算一类)和搜索词筛。搜索看名字、路径、出了什么问题、用到的模型、缺的节点类型、输入输出的名字。 */
export function filterWorkflows(
  workflows: readonly WorkflowFile[],
  { kind, query }: { kind: WorkflowKindFilter; query: string },
): WorkflowFile[] {
  const needle = query.trim().toLowerCase();
  return workflows.filter((flow) => {
    if (kind === "broken" ? !flow.problem : kind !== "all" && flow.kind !== kind) return false;
    if (!needle) return true;
    const haystack = [
      flow.label, flow.path, flow.problem,
      ...(flow.models ?? []).map((one) => one.name),
      ...(flow.missing_nodes ?? []).map((one) => one.type),
      ...(flow.inputs ?? []).map((one) => one.title),
      ...(flow.outputs ?? []).map((one) => one.title),
    ].join(" ").toLowerCase();
    return haystack.includes(needle);
  });
}

const byName = (a: WorkflowFile, b: WorkflowFile) =>
  a.label.localeCompare(b.label, undefined, { numeric: true, sensitivity: "base" }) || a.path.localeCompare(b.path);

/** 名字按自然顺序;改动时间新的在前;节点多的在前。一样的按名字。 */
export function sortWorkflows(workflows: readonly WorkflowFile[], sort: WorkflowSort): WorkflowFile[] {
  const out = [...workflows];
  if (sort === "modified") return out.sort((a, b) => (b.modified ?? -1) - (a.modified ?? -1) || byName(a, b));
  if (sort === "nodes") return out.sort((a, b) => (b.node_count ?? 0) - (a.node_count ?? 0) || byName(a, b));
  return out.sort(byName);
}

// --- 改那台机器上的文件 -----------------------------------------------------------

/** Windows 上文件名里不能有的字符(那台 ComfyUI 可能在 Windows 上);和宿主、插件那两道查的是同一份。 */
const BAD_SEGMENT = /[<>:"|?*\\]/;
const hasControl = (text: string) => [...text].some((char) => char.charCodeAt(0) < 32);

/** 输入框里的字 → workflows/ 里的相对路径:去掉首尾空白和开头的 `workflows/`,没写 `.json` 就补上。 */
export function workflowPathFrom(input: string): string {
  const text = input.trim().replace(/^workflows\//, "");
  return text && !text.toLowerCase().endsWith(".json") ? `${text}.json` : text;
}

/** 能用的路径:`/` 分段,每段不空、不是 `.` / `..`、不以点开头、首尾没有空白、没有 Windows 不收的字符。 */
export function validWorkflowPath(path: string): boolean {
  if (!path.toLowerCase().endsWith(".json") || path.length > 500) return false;
  return path.split("/").every((one) => one && one !== "." && one !== ".." && !one.startsWith(".") && one === one.trim() &&
    !BAD_SEGMENT.test(one) && !hasControl(one));
}

/** 一个不撞名的建议:`人像.json` → `人像 (1).json`、`人像 (2).json`…… */
export function freeWorkflowPath(path: string, taken: ReadonlySet<string>): string {
  const stem = path.replace(/\.json$/i, "");
  for (let index = 1; index < 1000; index += 1) {
    const candidate = `${stem} (${index}).json`;
    if (!taken.has(candidate)) return candidate;
  }
  return path;
}

/** 后端撞名回的 409(`detail.suggestion` 是建议名);不是这种就是 null。 */
export function conflictOf(error: unknown): { suggestion: string } | null {
  const { status, body } = (error ?? {}) as { status?: unknown; body?: unknown };
  if (status !== 409) return null;
  try {
    const detail = (JSON.parse(String(body ?? "")) as { detail?: { suggestion?: unknown } }).detail;
    return { suggestion: typeof detail?.suggestion === "string" ? detail.suggestion : "" };
  } catch {
    return { suggestion: "" };
  }
}
