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
      labels[role] = [...(labels[role] ?? []), one.label || item.node_title || `${item.class_type} #${item.node}`];
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
