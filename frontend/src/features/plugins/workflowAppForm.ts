/**
 * 应用表单的草稿(ADR 0038 §2):作者从一张工作流**全部能填的项**里挑几项、起名、排序、收窄可选值,标哪个输出节点是
 * 结果。编辑器(WorkflowAppEditor)只摆它;这里是纯函数 —— 从插件读到的那份起草、改、算出要写回去的样子和预览用的描述符。
 *
 * 预览不另造一套:按草稿拼出一份和生成目录**同形**的描述符(`parameter_keys` / `parameter_schema` / `source_limits` /
 * `source_labels` / `prompt`),交给 AI 工作台、画板、工作流节点用的同一组读法(lib/generationCapabilities)和同一组控件
 * (components/generation/parameterPanel)。插件那一侧怎么把应用表单变成目录,见 plugins/bundled/comfyui/tools/graph.describe。
 */
import type { GenerationOption, WorkflowAnnotate, WorkflowApp, WorkflowFillable } from "@/api/client";

/** 草稿里的一项:锚点、作者起的名字、是不是主提示词、收窄的可选值;`problem` 是读进来时就对不上的原因(工作流改过了)。 */
export interface AppItemDraft {
  key: string;
  node: string;
  input: string;
  label: string;
  main: boolean;
  /** 只许从这几项里挑;null = 不收窄 */
  choices: string[] | null;
  problem: string;
}

export interface AppDraft {
  title: string;
  description: string;
  items: AppItemDraft[];
  /** 标成结果的输出节点(「以后只要这张」) */
  results: string[];
}

/** 进参数表的那几种(`<节点 id>.<输入名>`);文字项标了主提示词时进的是宿主的提示词框。 */
const VALUE_KINDS = new Set(["text", "model", "number", "choice", "toggle"]);
/** 能收窄可选值的那几种:下拉、选模型文件的。 */
export const CHOICE_KINDS = new Set(["choice", "model"]);
/** 图级的项:用宿主自己的控件(种子框、尺寸下拉、跑几遍),名字是宿主的,不能改。 */
export const GRAPH_KINDS = new Set(["seed", "size", "runs"]);

/** 从插件读到的那份起草:文件里有应用表单就照它(对不上的那几项也留着,标着原因,作者自己决定去不去掉),没有就是空的。 */
export function initialDraft(data: WorkflowApp): AppDraft {
  const app = data.app ?? { status: "none" as const };
  const results = app.status === "ok" ? [...(app.results ?? [])] : [];
  if (app.status !== "ok" || !app.app) return { title: "", description: "", items: [], results };
  return {
    title: app.title ?? "",
    description: app.description ?? "",
    items: (app.items ?? []).map((one) => ({
      key: one.key,
      node: one.node ?? "",
      input: one.input,
      label: one.label ?? "",
      main: one.main === true,
      choices: one.choices ?? null,
      problem: one.problem ?? "",
    })),
    results,
  };
}

/** 一项能不能放进应用表单:子图里面的节点这一版不能(ADR 0038「这一版不做」)。 */
export function exposable(item: WorkflowFillable): boolean {
  return item.exposable !== false;
}

/** 挑进来一项,排在最后。认出来的提示词格缺省就是主提示词(写进宿主的提示词框)—— 同一角色已经有一格是主提示词时也是:
 *  同一句话写进每一格,和缺省的应用一样。 */
export function addItem(draft: AppDraft, item: WorkflowFillable): AppDraft {
  if (draft.items.some((one) => one.key === item.key)) return draft;
  const main = item.kind === "text" && Boolean(item.role);
  return {
    ...draft,
    items: [...draft.items, { key: item.key, node: item.node ?? "", input: item.input, label: "", main, choices: null, problem: "" }],
  };
}

/** 编辑器认的「主模型」目录:大模型、扩散模型。推荐表单里挑第一个选这几种文件的下拉。 */
const MAIN_MODEL_FOLDERS = ["checkpoints", "diffusion_models", "unet", "unet_gguf"];

/**
 * 「按推荐先挑一版」挑哪几项,按表单上的顺序:主提示词(认出来的提示词格,几处同一句)、反向提示词、主模型(第一个选大模型 /
 * 扩散模型文件的下拉)、种子、尺寸、跑几遍,和每一个读图 / 视频 / 音频 / 蒙版的槽位。子图里面的节点不挑(这一版放不进表单)。
 */
export function recommendedItems(data: WorkflowApp): WorkflowFillable[] {
  const items = (data.items ?? []).filter(exposable);
  const text = (role: string) => items.filter((one) => one.kind === "text" && one.role === role);
  const model = items.find((one) => one.kind === "model" && MAIN_MODEL_FOLDERS.includes(one.folder ?? ""));
  const graph = (kind: string) => items.filter((one) => one.kind === kind);
  return [
    ...text("prompt"),
    ...text("negative"),
    ...(model ? [model] : []),
    ...graph("seed"),
    ...graph("size"),
    ...graph("runs"),
    ...items.filter((one) => one.kind === "media"),
  ];
}

/** 把推荐的那几项加进草稿(已经在表单上的不重复加,排在已有的后面)。 */
export function addRecommended(draft: AppDraft, data: WorkflowApp): AppDraft {
  return recommendedItems(data).reduce(addItem, draft);
}

/** 没有应用表单时用的人看到的那张表(缺省的应用):全部能填的项,认出来的提示词格写进提示词框 —— 和插件的 default_form 同一条。 */
export function defaultDraft(data: WorkflowApp): AppDraft {
  return { title: "", description: "", items: (data.items ?? []).reduce(addItem, emptyDraft()).items, results: [] };
}

function emptyDraft(): AppDraft {
  return { title: "", description: "", items: [], results: [] };
}

export function removeItem(draft: AppDraft, key: string): AppDraft {
  return { ...draft, items: draft.items.filter((one) => one.key !== key) };
}

/** 往前(-1)/ 往后(+1)挪一格。到头了就不动。 */
export function moveItem(draft: AppDraft, key: string, delta: -1 | 1): AppDraft {
  const index = draft.items.findIndex((one) => one.key === key);
  const target = index + delta;
  if (index < 0 || target < 0 || target >= draft.items.length) return draft;
  const items = [...draft.items];
  [items[index], items[target]] = [items[target], items[index]];
  return { ...draft, items };
}

/** 挪到第 `index` 格(拖动松手的那一下)。不在表单上、或者没挪就不动。 */
export function moveItemTo(draft: AppDraft, key: string, index: number): AppDraft {
  const from = draft.items.findIndex((one) => one.key === key);
  const to = Math.max(0, Math.min(index, draft.items.length - 1));
  if (from < 0 || from === to) return draft;
  const items = [...draft.items];
  const [moved] = items.splice(from, 1);
  items.splice(to, 0, moved);
  return { ...draft, items };
}

export function updateItem(draft: AppDraft, key: string, patch: Partial<Pick<AppItemDraft, "label" | "main" | "choices">>): AppDraft {
  return { ...draft, items: draft.items.map((one) => (one.key === key ? { ...one, ...patch } : one)) };
}

export function toggleResult(draft: AppDraft, node: string): AppDraft {
  return {
    ...draft,
    results: draft.results.includes(node) ? draft.results.filter((one) => one !== node) : [...draft.results, node],
  };
}

/** 对不上的那几项全去掉(「一键去掉」);给了交回结果的输出节点(`outputs`),标在别的节点上的结果标记也去掉。 */
export function dropInvalid(draft: AppDraft, outputs?: string[]): AppDraft {
  return {
    ...draft,
    items: draft.items.filter((one) => !one.problem),
    results: outputs ? draft.results.filter((node) => outputs.includes(node)) : draft.results,
  };
}

/**
 * 收窄的可选值里有几个已经不在下拉里了(工作流改过、文件删了):只留还在的那几个(一个都不剩就不收窄),这一项就又能用了。
 * 别的原因(节点没了、被拉成连线)修不了,只能去掉。
 */
export function keepValidChoices(draft: AppDraft, key: string, options: string[]): AppDraft {
  return {
    ...draft,
    items: draft.items.map((one) => {
      if (one.key !== key) return one;
      const kept = (one.choices ?? []).filter((choice) => options.includes(choice));
      return { ...one, choices: kept.length > 0 ? kept : null, problem: "" };
    }),
  };
}

/** 失效的这一项能不能就地修好:节点和那一格都还在(插件还列着它),只是收窄的可选值里有的不在下拉里了。 */
export function fixableChoices(one: AppItemDraft, item: WorkflowFillable | undefined): string[] | null {
  if (!one.problem || !item || !CHOICE_KINDS.has(item.kind) || !one.choices?.length) return null;
  const declared = (item.spec as { enum?: unknown } | null | undefined)?.enum;
  return Array.isArray(declared) ? declared.map(String) : null;
}

/** 编辑器左边「工作流里能填的」按节点分的一组:节点给人看的名字(插件给的,用户起的标题优先)、节点号、类名(悬停排错用)。
 *  图级的项(种子、尺寸、跑几遍)没有节点,自成一组(`node` 是空串)。按在图里第一次出现的顺序。 */
export interface SourceGroup {
  node: string;
  label: string;
  classType: string;
  items: WorkflowFillable[];
}

export function sourceGroups(items: readonly WorkflowFillable[]): SourceGroup[] {
  const groups = new Map<string, SourceGroup>();
  for (const item of items) {
    const node = item.node ?? "";
    const group = groups.get(node) ?? {
      node,
      label: item.node_label || item.node_title || item.class_type || "",
      classType: item.class_type ?? "",
      items: [],
    };
    group.items.push(item);
    groups.set(node, group);
  }
  return [...groups.values()];
}

/** 一项在它那个节点的分组里叫什么:名字里重复的节点名(「参考图 · 人物」里的「人物」、「花式模糊 · 模糊半径」里的「花式模糊」)
 *  去掉;去完什么都不剩就照原样。 */
export function shortTitle(item: WorkflowFillable): string {
  const title = item.title || item.key;
  const node = item.node_label || "";
  const drop = new Set([node, `${node} #${item.node}`, item.node_title || "", `${item.class_type} #${item.node}`].filter(Boolean));
  const kept = title.split(" · ").filter((part) => !drop.has(part));
  return kept.length > 0 ? kept.join(" · ") : title;
}

/** 搜索「工作流里能填的」:名字、节点名、节点号、类名、输入名里有搜的字。 */
export function matchesSource(item: WorkflowFillable, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return [item.title, item.node_label, item.node_title, item.class_type, item.key, item.input]
    .some((one) => (one ?? "").toLowerCase().includes(needle));
}

/** 要写回去的样子。一项都没挑就是**去掉应用表单**(`app: null`),只留结果标记 —— 没挑的项照工作流原样跑。 */
export function annotatePayload(path: string, modified: number, draft: AppDraft): WorkflowAnnotate {
  return {
    path,
    modified,
    app: draft.items.length
      ? {
          title: draft.title.trim(),
          description: draft.description.trim(),
          items: draft.items.map((one) => ({
            node: one.node,
            input: one.input,
            label: one.label.trim(),
            main: one.main,
            choices: one.choices && one.choices.length > 0 ? one.choices : null,
          })),
        }
      : null,
    results: draft.results,
  };
}

/** 草稿和读进来的那份是不是一样(没改过就不用存)。 */
export function sameDraft(left: AppDraft, right: AppDraft): boolean {
  const norm = (draft: AppDraft) =>
    JSON.stringify({
      title: draft.title.trim(),
      description: draft.description.trim(),
      items: draft.items.map(({ key, label, main, choices }) => [key, label.trim(), main, choices]),
      results: [...draft.results].sort(),
    });
  return norm(left) === norm(right);
}

/** 后端回的「那张刚在 ComfyUI 里改过」(409,`detail.code === "stale"`):应用表单没存,要重新打开再改。 */
export function isStale(error: unknown): boolean {
  const { status, body } = (error ?? {}) as { status?: unknown; body?: unknown };
  if (status !== 409) return false;
  try {
    return (JSON.parse(String(body ?? "")) as { detail?: { code?: unknown } }).detail?.code === "stale";
  } catch {
    return false;
  }
}

/** 草稿里的一项按这张图的哪一项能填的项来(读进来时就对不上的那几项找不到)。 */
export function itemsByKey(data: WorkflowApp): Map<string, WorkflowFillable> {
  return new Map((data.items ?? []).map((one) => [one.key, one]));
}

/**
 * 按草稿拼一份和生成目录同形的描述符,给预览用:主提示词 → 宿主的提示词框(`prompt`),标了主提示词的反向提示词 →
 * `negative_prompt`,素材 → 每个角色几份、按顺序叫什么(`source_limits` / `source_labels`),种子 / 尺寸 / 跑几遍 →
 * 宿主自己的控件,其余 → `parameter_schema`(作者起的名字、收窄的可选值、都摆在第一屏)。对不上的项不进。
 */
export function previewOption(data: WorkflowApp, draft: AppDraft, instanceId: string): GenerationOption {
  const found = itemsByKey(data);
  const keys: string[] = [];
  const schema: Record<string, Record<string, unknown>> = {};
  const limits: Record<string, number> = {};
  const labels: Record<string, string[]> = {};
  const capabilities: Record<string, unknown> = {};
  let prompted = false;
  //: 主提示词里有一格存的是空的:不写就拿空话去跑 —— 要写(和插件的 prompt_requirement 同一个判据)
  let promptEmpty = false;
  for (const one of draft.items) {
    const item = found.get(one.key);
    if (!item || one.problem) continue;
    const spec = (item.spec ?? {}) as Record<string, unknown>;
    if (item.kind === "text" && one.main) {
      if (item.role === "negative") {
        if (!keys.includes("negative_prompt")) keys.push("negative_prompt");
      } else {
        prompted = true;
        promptEmpty ||= !(typeof spec.default === "string" && spec.default.trim());
      }
    } else if (item.kind === "media") {
      const role = item.role ?? "";
      if (!role) continue;
      if (!(role in limits)) keys.push(role);
      limits[role] = (limits[role] ?? 0) + 1;
      labels[role] = [...(labels[role] ?? []), one.label || item.node_title || `${item.node_label || item.class_type} #${item.node}`];
    } else if (item.kind === "seed") {
      keys.push("seed");
    } else if (item.kind === "size") {
      keys.push("size");
      const examples = Array.isArray(spec.examples) ? spec.examples.map(String) : [];
      capabilities.sizes = examples;
      if (typeof spec.default === "string") capabilities.default_size = spec.default;
    } else if (item.kind === "runs") {
      keys.push("num_images");
      capabilities.max_num_images = typeof spec.maximum === "number" ? spec.maximum : 4;
      capabilities.num_images_unit = "runs";
    } else if (VALUE_KINDS.has(item.kind)) {
      const own: Record<string, unknown> = { ...spec, title: one.label || item.title };
      delete own["x-advanced"];
      if (one.choices && one.choices.length > 0 && CHOICE_KINDS.has(item.kind)) own.enum = one.choices;
      keys.push(one.key);
      schema[one.key] = own;
    }
  }
  capabilities.parameter_keys = keys;
  if (Object.keys(schema).length > 0) capabilities.parameter_schema = schema;
  if (Object.keys(limits).length > 0) capabilities.source_limits = limits;
  if (Object.keys(labels).length > 0) capabilities.source_labels = labels;
  capabilities.prompt = prompted ? (promptEmpty ? "required" : "optional") : "none";
  return {
    id: `preview:${data.path}`,
    provider_profile_id: "",
    plugin_instance_id: instanceId,
    profile_name: "",
    provider: "",
    kind: data.kind || "image",
    model: data.path,
    label: draft.title.trim() || data.path,
    capabilities,
    adapter_available: true,
    capabilities_known: true,
    is_default: false,
  };
}
