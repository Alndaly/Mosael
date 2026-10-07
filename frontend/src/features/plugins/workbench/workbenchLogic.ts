/**
 * ComfyUI 工作台(ADR 0038 §3、§6)面板背后的纯函数:桥报来的选中节点 → 哪几格选的是模型文件;模型库按目录、搜索、底模家族
 * 筛;跑完的产出按来自的节点分组、标节点名;画布上的事件 → 正在跑哪个节点、第几步;「只要这个节点的图」→ 应用表单草稿只标这一个结果;
 * 运行按工作流分;缺失项定位到画布上的节点、按节点包分组。
 *
 * 桥报来的东西主进程已经规整过(electron/publish/comfyWorkbench.parseWorkbenchPoll);这里仍只当提示:节点名字以导出的那张图为准,
 * 产出来自哪个节点以插件读的历史为准(任务回执里的 `source_node`)。
 */
import type { Job, ModelFile, NodeEncoders, WorkflowNodePack } from "@/api/client";
import type { AppDraft } from "@/features/plugins/workflowAppForm";
import type { WorkbenchRun } from "@/features/plugins/workbench/workbenchSession";

export type WorkbenchNode = NonNullable<ComfyWorkbenchState["selection"]["node"]>;

/**
 * 选中节点上的下拉格子,按插件问它是哪个模型目录用的样子(节点类型 + 输入名),带上这个节点上下拉格子现在的值 —— 插件据此
 * 判,比如 CLIP 加载节点的 type 配哪几种文本编码器。界面不认识这些格子是干什么的。
 */
export function comboInputs(node: WorkbenchNode | null): { class_type: string; input: string; values: Record<string, string> }[] {
  if (!node) return [];
  const combos = node.widgets.filter((one) => one.combo);
  const values = Object.fromEntries(combos.flatMap((one) => (typeof one.value === "string" ? [[one.name, one.value]] : [])));
  return combos.map((one) => ({ class_type: node.type, input: one.name, values }));
}

/**
 * 选中节点上选模型文件的那几格(插件说了目录的):widget 名字、目录、现在的值;选文本编码器的那一格还有节点现在的 type 配
 * 哪几种(`encoders`,插件给的;别的格子是 null)。
 */
export interface ModelSlot {
  widget: string;
  folder: string;
  value: string;
  encoders: NodeEncoders | null;
}

export function modelSlots(
  node: WorkbenchNode | null,
  folders: readonly string[],
  encoders: readonly (NodeEncoders | null)[] = [],
): ModelSlot[] {
  const combos = node ? node.widgets.filter((one) => one.combo) : [];
  return combos.flatMap((widget, index) =>
    folders[index]
      ? [{ widget: widget.name, folder: folders[index], value: typeof widget.value === "string" ? widget.value : "", encoders: encoders[index] ?? null }]
      : [],
  );
}

/**
 * 一个文本编码器合不合这一格现在的 type:`fits` 在这个 type 的配方里,`any` ComfyUI 认出是它之后不看 type(建出来都一样,
 * 不算不合),`misfit` 不在配方里。不是选文本编码器的格子、认不出是哪一种的文件是 null:不排、不标。
 */
export type EncoderFit = "fits" | "any" | "misfit";

export function encoderFit(model: Pick<ModelFile, "encoder">, recipe: NodeEncoders | null): EncoderFit | null {
  const kind = model.encoder?.kind;
  if (!recipe || !kind) return null;
  if ((recipe.fits ?? []).includes(kind)) return "fits";
  return (recipe.any_type ?? []).includes(kind) ? "any" : "misfit";
}

/** 按配方排:在配方里的在前,不看 type 的、认不出的在中间,不在配方里的最后;同一档里照原来的先后。 */
export function byRecipe(models: readonly ModelFile[], recipe: NodeEncoders | null): ModelFile[] {
  if (!recipe) return [...models];
  const rank = (model: ModelFile) => {
    const fit = encoderFit(model, recipe);
    return fit === "fits" ? 0 : fit === "misfit" ? 2 : 1;
  };
  return [...models].sort((left, right) => rank(left) - rank(right));
}

/** ComfyUI 在 Windows 上报的相对路径用反斜杠:比较前统一(和 ModelThumb.normModelName 同一个规矩)。 */
const norm = (name: string) => name.replace(/\\/g, "/").trim();

/** 这个目录里有没有这个文件(名字按路径统一比较)。 */
export function presentIn(models: readonly ModelFile[], folder: string, name: string): boolean {
  if (!name) return true;
  const wanted = norm(name);
  return models.some((one) => one.folder === folder && norm(one.name) === wanted);
}

/** 模型库面板列哪些:这个目录的,名字 / 标题 / 触发词里有搜的字,底模家族对得上(`family` 空 = 不筛)。按名字排。 */
export function folderModels(
  models: readonly ModelFile[],
  folder: string,
  { query, family }: { query: string; family: string },
): ModelFile[] {
  const needle = query.trim().toLowerCase();
  return models
    .filter((one) => one.folder === folder)
    .filter((one) => !family || (one.family || "") === family)
    .filter((one) => !needle || `${one.name} ${one.title} ${(one.triggers ?? []).join(" ")}`.toLowerCase().includes(needle))
    .sort((left, right) => norm(left.name).localeCompare(norm(right.name)));
}

/** 这个目录里有哪几种底模家族(筛选用),按数量排;认不出家族的不列。 */
export function folderFamilies(models: readonly ModelFile[], folder: string): string[] {
  const counts = new Map<string, number>();
  for (const one of models) if (one.folder === folder && one.family) counts.set(one.family, (counts.get(one.family) ?? 0) + 1);
  return [...counts.entries()].sort((left, right) => right[1] - left[1]).map(([family]) => family);
}

/** 导出的那张图(界面格式)里每个节点叫什么:节点上的标题,没有就是类型。 */
export function nodeLabels(workflow: Record<string, unknown> | null | undefined): Map<string, string> {
  const labels = new Map<string, string>();
  const nodes = Array.isArray(workflow?.nodes) ? (workflow.nodes as unknown[]) : [];
  for (const raw of nodes) {
    if (!raw || typeof raw !== "object") continue;
    const node = raw as { id?: unknown; title?: unknown; type?: unknown };
    if (node.id === undefined || node.id === null) continue;
    const title = typeof node.title === "string" && node.title.trim() ? node.title.trim() : "";
    labels.set(String(node.id), title || (typeof node.type === "string" ? node.type : ""));
  }
  return labels;
}

/** 一组产出:来自哪个节点、节点叫什么、哪几份素材。 */
export interface OutputGroup {
  node: string;
  label: string;
  assets: string[];
}

/**
 * 跑完的那次交回的产出,按来自的节点分组(任务回执里的 `output_parameters[].parameters.source_node`,插件读的历史为准),
 * 按第一次出现的顺序。说不出来自哪个节点的放在最后一组(`node` 是空串)。
 */
export function outputGroups(job: Pick<Job, "result"> | null | undefined, labels: Map<string, string>): OutputGroup[] {
  const result = (job?.result ?? {}) as { asset_ids?: unknown; output_parameters?: unknown };
  const ids = Array.isArray(result.asset_ids) ? result.asset_ids.filter((one): one is string => typeof one === "string") : [];
  const sources = new Map<string, string>();
  for (const raw of Array.isArray(result.output_parameters) ? result.output_parameters : []) {
    const entry = raw as { asset_id?: unknown; parameters?: { source_node?: unknown } };
    const node = entry?.parameters?.source_node;
    if (typeof entry?.asset_id === "string" && (typeof node === "string" || typeof node === "number")) {
      sources.set(entry.asset_id, String(node));
    }
  }
  const groups = new Map<string, OutputGroup>();
  for (const id of ids) {
    const node = sources.get(id) ?? "";
    const group = groups.get(node) ?? { node, label: node ? labels.get(node) ?? "" : "", assets: [] };
    group.assets.push(id);
    groups.set(node, group);
  }
  return [...groups.values()].sort((left, right) => Number(left.node === "") - Number(right.node === ""));
}

/** 画布上的事件看出来的「正在跑什么」:最近一次开始之后,正在跑的节点和它的步数;跑完 / 出错 / 中断了就是 null。 */
export interface LiveProgress {
  promptId: string;
  node: string;
  value: number;
  max: number;
}

export function liveProgress(events: readonly ComfyWorkbenchEvent[], promptId?: string): LiveProgress | null {
  let current = null as LiveProgress | null;
  for (const event of events) {
    if (promptId && event.promptId && event.promptId !== promptId) continue;
    const previous: LiveProgress | null = current;
    if (event.type === "execution_start") current = { promptId: event.promptId, node: "", value: 0, max: 0 };
    else if (event.type === "executing") {
      current = event.node ? { promptId: event.promptId || previous?.promptId || "", node: event.node, value: 0, max: 0 } : null;
    } else if (event.type === "progress" && previous) {
      current = { ...previous, node: event.node || previous.node, value: event.value ?? 0, max: event.max ?? 0 };
    } else if (["execution_success", "execution_error", "execution_interrupted"].includes(event.type)) current = null;
  }
  return current;
}

/** 「只要这个节点的图」:这张工作流的结果只标这一个输出节点(清掉别的节点上的,ADR 0038 §5)。应用表单的别的部分不动。 */
export function onlyResult(draft: AppDraft, node: string): AppDraft {
  return { ...draft, results: [node] };
}

/** 撤销:这个节点不再标成结果(别的节点上的标记不动)。 */
export function withoutResult(draft: AppDraft, node: string): AppDraft {
  return { ...draft, results: draft.results.filter((one) => one !== node) };
}

/** 一次跑出的全部产出(按回执里的顺序)交给看大图:标题带来源节点和第几张(「PreviewImage #12 · 1/2」)。 */
export function runGallery(
  groups: readonly OutputGroup[],
  nodeName: (node: string) => string,
  unknownNode: string,
): { asset: string; title: string }[] {
  const all = groups.flatMap((group) => group.assets.map((asset) => ({ asset, node: group.node })));
  return all.map((one, index) => ({
    asset: one.asset,
    title: `${one.node ? nodeName(one.node) : unknownNode} · ${index + 1}/${all.length}`,
  }));
}

/** 「运行与结果」按工作流分:画布上开着的这一张跑过的在前,别的那几张各一组(最近跑的那张在前),都还留着看得到。 */
export function runsByWorkflow(
  runs: readonly WorkbenchRun[],
  current: string,
): { current: WorkbenchRun[]; others: { key: string; name: string; runs: WorkbenchRun[] }[] } {
  const others = new Map<string, { key: string; name: string; runs: WorkbenchRun[] }>();
  const mine: WorkbenchRun[] = [];
  for (const run of runs) {
    if (run.workflowKey === current) {
      mine.push(run);
      continue;
    }
    const group = others.get(run.workflowKey) ?? { key: run.workflowKey, name: run.workflowName || run.path, runs: [] };
    group.runs.push(run);
    others.set(run.workflowKey, group);
  }
  return { current: mine, others: [...others.values()] };
}

// ---- 缺失项:定位到画布上的节点、按节点包分组 ---------------------------------------------------------

/** 画布上的一个节点:在根图上(`subgraph` 是 null),或在某张子图里(子图的 id 和名字)。 */
export interface CanvasSpot {
  node: string;
  subgraph: string | null;
  subgraphName: string;
}

type RawNode = { id?: unknown; type?: unknown; widgets_values?: unknown };

/** 导出的那张图(界面格式)里的每个节点:根图上的,和 `definitions.subgraphs` 里每张子图的。 */
function canvasNodes(workflow: Record<string, unknown> | null | undefined): { raw: RawNode; spot: CanvasSpot }[] {
  const out: { raw: RawNode; spot: CanvasSpot }[] = [];
  const add = (nodes: unknown, subgraph: string | null, subgraphName: string) => {
    for (const raw of Array.isArray(nodes) ? nodes : []) {
      if (!raw || typeof raw !== "object") continue;
      const node = raw as RawNode;
      if (node.id === undefined || node.id === null) continue;
      out.push({ raw: node, spot: { node: String(node.id), subgraph, subgraphName } });
    }
  };
  add(workflow?.nodes, null, "");
  const subgraphs = (workflow?.definitions as { subgraphs?: unknown } | undefined)?.subgraphs;
  for (const raw of Array.isArray(subgraphs) ? subgraphs : []) {
    const sub = raw as { id?: unknown; name?: unknown; nodes?: unknown };
    if (typeof sub?.id !== "string") continue;
    add(sub.nodes, sub.id, typeof sub.name === "string" && sub.name ? sub.name : sub.id);
  }
  return out;
}

/** 这种节点类型在画布上的每一处(缺的节点「定位」用)。 */
export function nodesOfType(workflow: Record<string, unknown> | null | undefined, type: string): CanvasSpot[] {
  return canvasNodes(workflow).filter(({ raw }) => raw.type === type).map(({ spot }) => spot);
}

/** 哪几个节点的 widget 里填着这个模型文件(名字按路径统一比较;只写了文件名的也认)。缺的模型「定位」用。 */
export function nodesUsingModel(workflow: Record<string, unknown> | null | undefined, name: string): CanvasSpot[] {
  const wanted = norm(name);
  const base = wanted.split("/").pop() ?? wanted;
  const matches = (value: unknown) => {
    if (typeof value !== "string" || !value) return false;
    const one = norm(value);
    return one === wanted || (one.split("/").pop() ?? one) === base;
  };
  return canvasNodes(workflow)
    .filter(({ raw }) => {
      const values = raw.widgets_values;
      const list = Array.isArray(values) ? values : values && typeof values === "object" ? Object.values(values) : [];
      return list.some(matches);
    })
    .map(({ spot }) => spot);
}

/** 缺的节点按出自的节点包分:同一个包的几种节点一起装;认不出包的各自一组(`packs` 是空的)。 */
export function missingByPack<T extends { type: string; count?: number; packs?: WorkflowNodePack[] }>(
  nodes: readonly T[],
): { key: string; packs: WorkflowNodePack[]; nodes: T[] }[] {
  const groups = new Map<string, { key: string; packs: WorkflowNodePack[]; nodes: T[] }>();
  for (const node of nodes) {
    const packs = node.packs ?? [];
    //: 一种节点可能出自好几个包(映射里几个包都有同名的):那几个一起当一组,装哪个由人挑
    const key = packs.length ? packs.map((one) => one.id).sort().join("\n") : `type:${node.type}`;
    const group = groups.get(key) ?? { key, packs, nodes: [] };
    group.nodes.push(node);
    groups.set(key, group);
  }
  return [...groups.values()].sort((left, right) => Number(left.packs.length === 0) - Number(right.packs.length === 0));
}

/** 节点包的主页:映射里只在 git 上的包,id 就是仓库地址;登记在 Comfy Registry 上的是包名。 */
export function packPage(id: string): string {
  return /^https?:\/\//i.test(id) ? id.replace(/\.git$/i, "") : `https://registry.comfy.org/nodes/${encodeURIComponent(id)}`;
}

/** 工作流库里认的路径(`workflows/` 下的相对路径):桥报的是去掉前缀的那一段,空串是没存过。 */
export const savedPath = (state: ComfyWorkbenchState | null): string => state?.workflow?.path ?? "";
