import type { WorkflowFile } from "@/api/client";

/**
 * 工作流库列表那一页「看哪些、按什么顺序」的纯函数:文件夹树怎么排、哪些算「缺东西」、筛和排、改文件夹时的路径。
 * 界面(WorkflowLibrary)只管摆。
 */

/** 左栏的「全部」「缺节点或模型」「回收站」。文件夹的值带着前缀(`folder:video`),和它们撞不上。 */
export const ALL_WORKFLOWS = "__all__";
export const PROBLEMS_VIEW = "__problems__";
export const TRASH_VIEW = "__trash__";
const FOLDER_VIEW = "folder:";

/** 左栏里一个文件夹的值;反过来认出是哪个文件夹(不是文件夹回 null)。 */
export const folderView = (path: string) => `${FOLDER_VIEW}${path}`;
export const folderOfView = (view: string): string | null => (view.startsWith(FOLDER_VIEW) ? view.slice(FOLDER_VIEW.length) : null);

export const WORKFLOW_KINDS = ["all", "image", "video", "audio", "broken"] as const;
export type WorkflowKindFilter = (typeof WORKFLOW_KINDS)[number];

export const WORKFLOW_SORTS = ["name", "modified", "nodes"] as const;
export type WorkflowSort = (typeof WORKFLOW_SORTS)[number];

/** 缺节点或缺模型(跑不起来、或跑起来要先补东西)。 */
export const lacksSomething = (flow: WorkflowFile) => (flow.missing_nodes?.length ?? 0) > 0 || (flow.missing_models?.length ?? 0) > 0;

/** 这个路径(一张工作流、一个文件)在不在这个文件夹里 —— 子文件夹里的也算。 */
export const inFolder = (path: string, folder: string) => path.startsWith(`${folder}/`);

const natural = (a: string, b: string) => a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" }) || a.localeCompare(b);

/** 左栏的一个文件夹:全路径、最后一段、第几层(顶层是 0)、里面(连同各级子文件夹)有几张工作流。 */
export type WorkflowFolderRow = { path: string; name: string; depth: number; count: number };

/**
 * 左栏的文件夹树,和 ComfyUI 自己的侧栏一样按目录摆:一层层往下,同一层按名字的自然顺序(不按数量 —— 拖卡片过去时
 * 目标不能挪来挪去)。插件报的(空的也在)加上每张工作流所在的,各级上级补齐。数量算上子文件夹里的。
 */
export function folderTree(folders: readonly string[], workflows: readonly WorkflowFile[]): WorkflowFolderRow[] {
  const all = new Set<string>();
  for (const one of [...folders, ...workflows.map((flow) => flow.folder)]) {
    const parts = (one ?? "").split("/").filter(Boolean);
    for (let depth = 1; depth <= parts.length; depth += 1) all.add(parts.slice(0, depth).join("/"));
  }
  const children = new Map<string, string[]>();
  for (const path of all) {
    const parent = parentOf(path);
    children.set(parent, [...(children.get(parent) ?? []), path]);
  }
  const rows: WorkflowFolderRow[] = [];
  const walk = (parent: string, depth: number) => {
    for (const path of (children.get(parent) ?? []).sort((a, b) => natural(baseName(a), baseName(b)))) {
      rows.push({ path, name: baseName(path), depth, count: workflows.filter((flow) => inFolder(flow.path, path)).length });
      walk(path, depth + 1);
    }
  };
  walk("", 0);
  return rows;
}

/** 左栏选中的那一项里有哪些:全部、缺东西的、一个文件夹(连同子文件夹里的)。 */
export function inView(workflows: readonly WorkflowFile[], view: string): WorkflowFile[] {
  if (view === ALL_WORKFLOWS) return [...workflows];
  if (view === PROBLEMS_VIEW) return workflows.filter(lacksSomething);
  const folder = folderOfView(view);
  return folder === null ? [] : workflows.filter((flow) => inFolder(flow.path, folder));
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

/** 409 的 `detail`(撞名的建议名、不空的文件夹里有几个);不是 409 回 null。 */
function conflictDetail(error: unknown): { code?: unknown; suggestion?: unknown; count?: unknown } | null {
  const { status, body } = (error ?? {}) as { status?: unknown; body?: unknown };
  if (status !== 409) return null;
  try {
    const detail = (JSON.parse(String(body ?? "")) as { detail?: unknown }).detail;
    return detail && typeof detail === "object" ? detail : {};
  } catch {
    return {};
  }
}

/** 后端撞名回的 409(`detail.suggestion` 是建议名);不是这种(不是 409、或者是「文件夹不空」那种)就是 null。 */
export function conflictOf(error: unknown): { suggestion: string } | null {
  const detail = conflictDetail(error);
  if (!detail || (detail.code !== undefined && detail.code !== "exists")) return null;
  return { suggestion: typeof detail.suggestion === "string" ? detail.suggestion : "" };
}

/** 要删的文件夹里还有文件(后端回的 409 `not_empty`,带着几个);不是这种就是 null。 */
export function notEmptyOf(error: unknown): { count: number } | null {
  const detail = conflictDetail(error);
  if (!detail || detail.code !== "not_empty") return null;
  return { count: typeof detail.count === "number" ? detail.count : 1 };
}

// --- 文件夹 -------------------------------------------------------------------------

/** 路径的最后一段(文件夹名、`名字.json`);上一级(顶层的上一级是 `""`,就是 workflows/ 本身)。 */
export const baseName = (path: string) => path.slice(path.lastIndexOf("/") + 1);
export const parentOf = (path: string) => (path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "");
/** 一个文件夹里的一个名字;文件夹是 `""` 就在 workflows/ 顶上。 */
export const joinPath = (folder: string, name: string) => (folder ? `${folder}/${name}` : name);

/** 输入框里的字 → 文件夹路径:去掉首尾空白、开头的 `workflows/` 和末尾的 `/`。 */
export function folderPathFrom(input: string): string {
  return input.trim().replace(/^workflows\//, "").replace(/\/+$/, "");
}

/** 能用的文件夹路径:和工作流路径同一套分段规则,只是不以 `.json` 结尾(那像一张工作流)。 */
export function validFolderPath(path: string): boolean {
  if (!path || path.length > 400 || path.toLowerCase().endsWith(".json")) return false;
  return path.split("/").every((one) => one && one !== "." && one !== ".." && !one.startsWith(".") && one === one.trim() &&
    !BAD_SEGMENT.test(one) && !hasControl(one));
}

/** 一个不撞名的文件夹名(不分大小写比:那台机器可能是 Windows):`人像` → `人像 (1)`…… */
export function freeFolderPath(path: string, taken: readonly string[]): string {
  const lowered = new Set(taken.map((one) => one.toLowerCase()));
  if (!lowered.has(path.toLowerCase())) return path;
  for (let index = 1; index < 1000; index += 1) {
    const candidate = `${path} (${index})`;
    if (!lowered.has(candidate.toLowerCase())) return candidate;
  }
  return path;
}

/** 那台机器上这个文件夹里(连同子文件夹)的文件:工作流和别的文件(压缩包)都算 —— 有一个就不能删。 */
export function filesIn(folder: string, paths: readonly string[]): number {
  return paths.filter((path) => inFolder(path, folder)).length;
}
