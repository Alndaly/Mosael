/**
 * 读生成模型的 capabilities。
 *
 * 目录(`/api/generation/models`)声明每个模型支持哪些参数、可选值和默认值:
 * `parameter_keys` / `aspect_ratios` / `resolutions` / `duration_seconds` …
 * 界面据此渲染,而不是各处硬编一份"视频有哪些比例"——硬编的那份会在目录更新后悄悄过时。
 *
 * 抽到这里是因为有两个消费方:AI Studio 的生成面板,和工作流「AI 生成素材」节点的参数区。
 * 同一份规则解释两遍,迟早会在某一处漏掉新参数。
 */
import type { GenerationOption } from "@/api/client";
import type { MessageKey } from "@/app/messages";

/**
 * 生成的种类:图像、视频、音频(音乐 / BGM / 音效 / 给视频配声,见 ADR 0022)。和后端
 * domain/generation/catalog.GENERATION_KINDS 同一份;设置页、工作流节点按它逐种列出,不再各写一份
 * `["image", "video"]` —— 那样加一种介质时,漏改的那一处只会让它在某个入口上悄悄不见。
 */
export const GENERATION_KINDS = ["image", "video", "audio"] as const;
export type GenerationKind = (typeof GENERATION_KINDS)[number];

/**
 * **目录没声明可选值时,这里不再替它编一个。**
 *
 * 这三个常量原本是"给一个能跑的常见值,而不是空"。代价是:一个参数键只要出现、而清单缺席,
 * 界面就会摆出一个只有 1024x1024 / 720p / 16:9 的下拉,取第一项当默认并提交 —— 于是
 * "我们知道这个模型收 size" 悄悄变成 "我们声称它是 1024x1024",而用户一项都没选过。
 *
 * 量过:39 份内置档案里**没有一份**声明了 size / resolution / aspect_ratio 却不给清单
 * (只有 duration 会,而它走 min/max 区间那条路)。所以这三个兜底对已知模型是死代码,
 * 它们只在**未知模型**上开火 —— 也就是最不该替它编值的那一种。
 *
 * 空清单的含义因此变成"这一项能发,但有哪些取值我们不知道",由界面渲染成一个自由输入框:
 * 摆出来,但在用户填之前不带任何值。见 ADR 0015。
 */
export const UNDECLARED: string[] = [];

/**
 * 生成模型选择器该落在哪一项:**存着的那个 → 这个人设的默认 → 没有**。
 *
 * **不取第一项。** 清单按连接名排序,排在第一的那个不是谁的选择 —— 画板的出图格就是这么默认挑中了
 * 147ai 上的 `claude-opus-4-6`,而用户在设置里明明设过默认生图模型(后端没点名模型时用的也是它)。
 * 默认由后端标在选项上(`is_default`,同一个 resolve_default);一项都没标就回 null,选择器显示
 * 「选择模型」让人选。棘轮:`generationPickerDefault.test.ts`。
 *
 * `saved` 认存着的那一项(画板格的表单、会话记着的模型……);它不在清单里了(删了、停用了、
 * 不再被认成这种生成)就当没存,往下落到默认。`kind` 给了就只认这种生成的默认 —— AI 工作台的
 * 清单是三种生成合在一起的。
 */
export function pickGenerationOption<T extends GenerationOption>(
  options: readonly T[],
  { saved, kind }: { saved?: ((option: T) => boolean) | null; kind?: string } = {},
): T | null {
  const kept = saved ? options.find(saved) : undefined;
  if (kept) return kept;
  return options.find((option) => option.is_default && (!kind || option.kind === kind)) ?? null;
}

export function capabilityList(model: GenerationOption | null, key: string, fallback: string[]): string[] {
  const value = model?.capabilities?.[key];
  if (!Array.isArray(value)) return fallback;
  const items = value.map((item) => String(item).trim()).filter(Boolean);
  return items.length > 0 ? items : fallback;
}

export function capabilityNumberList(model: GenerationOption | null, key: string, fallback: number[]): number[] {
  const value = model?.capabilities?.[key];
  if (!Array.isArray(value)) return fallback;
  const items = value.map((item) => Number(item)).filter((item) => Number.isFinite(item) && item > 0);
  return items.length > 0 ? items : fallback;
}

export function capabilityString(model: GenerationOption | null, key: string, fallback: string): string {
  const value = model?.capabilities?.[key];
  return typeof value === "string" ? value : fallback;
}

export function capabilityNumber(model: GenerationOption | null, key: string, fallback: number): number {
  const value = Number(model?.capabilities?.[key]);
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

/** 布尔默认值也属于模型契约。缺失时使用调用方给的保守默认。 */
export function capabilityBoolean(model: GenerationOption | null, key: string, fallback = false): boolean {
  const value = model?.capabilities?.[key];
  return typeof value === "boolean" ? value : fallback;
}

/**
 * 这个角色最多能挂几份。目录里没写就是 1 —— **保守的那一边**:多挂一份的下场是提交时被拒,
 * 少挂一份只是少一张参考图。
 *
 * 数字来自各家接口自己的报错(见后端 domain/generation/catalog 的 source_limits),
 * 不是我们定的:火山和海螺给九张参考图,万相给参考图 + 参考视频合计五份。
 */
/**
 * 这个角色**能挂几份**。
 *
 * **不是支持判定。** 没声明的角色它返回兜底的 1 —— 想问「这个模型认不认某个角色」,
 * 用 supportsParameter(它查描述符的 parameter_keys)。两者混用会让图片模型也长出首尾帧槽。
 */
export function sourceLimit(model: GenerationOption | null, role: string): number {
  const limits = model?.capabilities?.source_limits;
  if (!limits || typeof limits !== "object") return 1;
  const value = Number((limits as Record<string, unknown>)[role]);
  return Number.isFinite(value) && value > 0 ? Math.floor(value) : 1;
}

/**
 * 这个角色的槽位**按顺序叫什么**(描述符的 `source_labels`,ADR 0038 §4):ComfyUI 一张工作流有十个读图节点时,
 * 它们是「人物」「背景」……而不是十个一样的「参考图」。第 i 个名字是第 i 格的提示 —— AI 工作台、画板、工作流节点
 * 三处都照它标。没声明(多数模型)是空数组;某一格没有名字是空串。通用的:哪个插件给了都用。
 */
export function sourceLabels(model: GenerationOption | null, role: string): string[] {
  const table = model?.capabilities?.source_labels;
  if (!table || typeof table !== "object") return [];
  const names = (table as Record<string, unknown>)[role];
  return Array.isArray(names) ? names.map((one) => (typeof one === "string" ? one : "")) : [];
}

/**
 * 互斥的角色分组。同一次生成只能用其中一组。
 *
 * 首尾帧决定成片的第一格和最后一格;参考素材一帧都不出现在成片里,只影响风格与主体 ——
 * 火山把这条画成硬约束(`first/last frame content cannot be mixed with reference media
 * content`)。界面照着它把另一组灰掉,免得用户挂满了才在提交时吃一个英文 400。
 */
export function exclusiveSourceGroups(model: GenerationOption | null): string[][] {
  const groups = model?.capabilities?.exclusive_source_groups;
  if (!Array.isArray(groups)) return [];
  return groups
    .filter((group): group is unknown[] => Array.isArray(group))
    .map((group) => group.map((role) => String(role)).filter(Boolean))
    .filter((group) => group.length > 0);
}

export function parameterKeys(model: GenerationOption | null): string[] {
  return capabilityList(model, "parameter_keys", []);
}

export function supportsParameter(model: GenerationOption | null, key: string) {
  if (key === "generate_audio" && model?.capabilities?.supports_generate_audio === true) return true;
  const declared = model?.capabilities?.parameter_keys;
  // 参数描述符是当前接口契约。缺失与明确为空都表示“不要猜”，否则前端会主动发送
  // 供应商未声明的尺寸、时长或素材角色，最终只会得到一次可以提前避免的 400。
  if (!Array.isArray(declared)) return false;
  return declared.map(String).includes(key);
}

/**
 * 这个模型对**提示词**的要求(描述符的 `prompt`,和后端 catalog.PROMPT_MODES 同一份):
 *
 * - `required`(没写就是它):要写一段描述;会唱歌词的模型(参数里有 `lyrics`)只给歌词也行;
 * - `optional`:可以不写 —— 给视频配声、按素材出结果的模型,写了是锦上添花;
 * - `none`:这个模型不收提示词(ComfyUI 里的放大、抠图这类工作流)—— 框不摆,发出去的是空串。
 *
 * 三个界面(AI 工作台、画板、工作流节点)都照它摆提示词框、判能不能提交;后端
 * operations.validate_text_inputs 用同一套规矩再判一遍。
 */
export type PromptMode = "required" | "optional" | "none";

export function promptMode(model: GenerationOption | null): PromptMode {
  const value = model?.capabilities?.prompt;
  return value === "optional" || value === "none" ? value : "required";
}

/** 真正发出去的提示词:不收提示词的模型发空串 —— 框藏起来之前写过的字不该悄悄跟着发出去。 */
export function promptToSend(model: GenerationOption | null, prompt: string): string {
  return promptMode(model) === "none" ? "" : prompt;
}

/**
 * 字够不够提交。和后端 validate_text_inputs 是同一套判据(后端仍会再判一遍):
 * 提示词按 `promptMode`;要描述的模型里,会唱歌词的只给歌词也行;纯音乐只剩描述可依,所以要描述。
 */
export function hasEnoughText(
  model: GenerationOption | null,
  prompt: string,
  lyrics = "",
  instrumental = false,
): boolean {
  const mode = promptMode(model);
  if (mode !== "required") return true;
  if (prompt.trim()) return true;
  return !instrumental && Boolean(lyrics.trim()) && supportsParameter(model, "lyrics");
}

/** 需要开关控件的参数。参数类型也是能力契约的一部分，不能在各页面各抄一张名单。 */
export function booleanParameterKeys(model: GenerationOption | null): string[] {
  const value = model?.capabilities?.boolean_parameters;
  if (!Array.isArray(value)) return [];
  return value.map(String).filter((key) => key && supportsParameter(model, key));
}

/** 供应商特有的枚举参数，例如 OpenAI quality/background/output_format。 */
export function parameterChoiceEntries(model: GenerationOption | null): Array<[string, string[]]> {
  const value = model?.capabilities?.parameter_choices;
  if (!value || typeof value !== "object") return [];
  return Object.entries(value as Record<string, unknown>)
    .filter(([key, choices]) => supportsParameter(model, key) && Array.isArray(choices))
    .map(([key, choices]) => [key, (choices as unknown[]).map(String).filter(Boolean)] as [string, string[]])
    .filter(([, choices]) => choices.length > 0);
}

/**
 * 模型**自己声明的**参数(`parameter_schema`)。
 *
 * 内置目录里的参数是宿主的词汇(尺寸、时长、种子……),各有专门的控件。而插件提供的生成供应商
 * (ADR 0020)每个模型有自己的一套:ComfyUI 的一张工作流有它自己的采样器、步数、CFG、帧数。
 * 插件用 JSON Schema 片段说清楚它们(类型、范围、可选值、默认值、给人看的名字),三个界面
 * (AI 工作台、画板、工作流节点)都照这一份渲染 —— 不认识任何一家,也不为某一家开分支。
 */
export type DeclaredParameterType = "integer" | "number" | "string" | "boolean";

export interface DeclaredParameter {
  key: string;
  type: DeclaredParameterType;
  /** 界面上的名字:插件给的 title,没有就是键本身。 */
  label: string;
  description: string;
  /** 插件说的默认值 —— **只用作占位提示**,不替用户提交(ADR 0015:没设过的不发)。 */
  defaultValue: string | number | boolean | undefined;
  minimum?: number;
  maximum?: number;
  step?: number;
  options: string[];
  /** 可选值给人看的名字(插件的 `x-enum-labels`,宿主已按语言挑好):ComfyUI「结果取自」的选项是节点 id,
   *  看到的是节点标题。没有名字的可选值照原样显示。 */
  optionLabels: Record<string, string>;
  multiline: boolean;
  advanced: boolean;
  /** 这一格选的是哪个模型目录的文件(插件的 `x-model-folder`,ComfyUI 的 checkpoints / loras……):表单据此从
   *  那个连接的模型库取缩略图、底模和触发词。不是选模型文件的格子没有。 */
  modelFolder?: string;
}

const DECLARED_TYPES: readonly DeclaredParameterType[] = ["integer", "number", "string", "boolean"];

function finiteNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function optionLabels(raw: unknown): Record<string, string> {
  if (!raw || typeof raw !== "object") return {};
  return Object.fromEntries(
    Object.entries(raw as Record<string, unknown>).filter((entry): entry is [string, string] => typeof entry[1] === "string" && entry[1] !== ""),
  );
}

/** 这个模型声明的那些参数,常用的在前、「高级」的在后(两段内部保持插件给的顺序)。 */
export function declaredParameters(model: GenerationOption | null): DeclaredParameter[] {
  const schema = model?.capabilities?.parameter_schema;
  if (!schema || typeof schema !== "object") return [];
  const out: DeclaredParameter[] = [];
  for (const [key, raw] of Object.entries(schema as Record<string, unknown>)) {
    if (!raw || typeof raw !== "object" || !supportsParameter(model, key)) continue;
    const spec = raw as Record<string, unknown>;
    const type = spec.type as DeclaredParameterType;
    if (!DECLARED_TYPES.includes(type)) continue;
    const fallback = spec.default;
    out.push({
      key,
      type,
      label: typeof spec.title === "string" && spec.title.trim() ? spec.title : key,
      description: typeof spec.description === "string" ? spec.description : "",
      defaultValue:
        typeof fallback === "string" || typeof fallback === "number" || typeof fallback === "boolean" ? fallback : undefined,
      minimum: finiteNumber(spec.minimum),
      maximum: finiteNumber(spec.maximum),
      step: finiteNumber(spec.multipleOf) ?? (type === "integer" ? 1 : undefined),
      options: Array.isArray(spec.enum) ? spec.enum.map(String) : [],
      optionLabels: optionLabels(spec["x-enum-labels"]),
      multiline: spec["x-multiline"] === true,
      advanced: spec["x-advanced"] === true,
      ...(typeof spec["x-model-folder"] === "string" && spec["x-model-folder"] ? { modelFolder: spec["x-model-folder"] } : {}),
    });
  }
  return [...out.filter((one) => !one.advanced), ...out.filter((one) => one.advanced)];
}

/**
 * 把 LoRA 的触发词加进提示词:接在末尾、逗号隔开;提示词里已经有的(按词认,不分大小写)不重复加。
 */
export function withTriggerWords(prompt: string, words: string[]): string {
  const base = prompt.replace(/[\s,，]+$/u, "");
  const present = (word: string) => {
    const escaped = word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return new RegExp(`(^|[^\\p{L}\\p{N}_])${escaped}(?=[^\\p{L}\\p{N}_]|$)`, "iu").test(base);
  };
  const added = words.map((word) => word.trim()).filter((word, index, all) => word && all.indexOf(word) === index && !present(word));
  if (added.length === 0) return prompt;
  return base ? `${base}, ${added.join(", ")}` : added.join(", ");
}

/**
 * 控件里的一段文字 → 按声明的类型发出去的值。空串 = **不设**(不发,让模型用它自己的默认)。
 *
 * 不能走 `parseGenerationParameterInput`:那个按「长得像数字就当数字」猜,而一个声明成文本的
 * 参数填了 `123` 就会被发成数字,提交时被校验器按类型拦下。这里类型是声明给的,不用猜。
 */
export function declaredParameterValue(
  parameter: DeclaredParameter,
  text: string,
): string | number | boolean | undefined {
  if (text === "") return undefined;
  if (parameter.type === "boolean") return text === "true";
  if (parameter.type === "integer" || parameter.type === "number") {
    const value = Number(text);
    if (!Number.isFinite(value)) return undefined;
    return parameter.type === "integer" ? Math.trunc(value) : value;
  }
  return text;
}

/** 这个模型能出哪些尺寸。**不限图像** —— 万相视频收的也是 `宽*高` 的像素对,
 *  而名字里带 image 会让人以为视频不该有这一栏(它此前就是这么被漏掉的)。 */
export function sizeOptions(model: GenerationOption | null): string[] {
  if (!supportsParameter(model, "size")) return [];
  return capabilityList(model, "sizes", UNDECLARED);
}

/**
 * 尺寸是不是**推荐的几档、手填的也收**(描述符的 `custom_size`,ComfyUI 的工作流就是:任意宽高,插件按 8 的倍数取整)。
 * 是的话交回每边的下限;只给了推荐清单的模型(多数云端接口只收那几档)回 null。
 */
export function customSizeRule(model: GenerationOption | null): { minimum: number } | null {
  if (!supportsParameter(model, "size")) return null;
  const rule = (model?.capabilities as Record<string, unknown> | undefined)?.custom_size;
  if (!rule || typeof rule !== "object") return null;
  const minimum = Number((rule as Record<string, unknown>).minimum);
  return { minimum: Number.isFinite(minimum) && minimum >= 1 ? minimum : 1 };
}

/** 手填的尺寸:`768x1024`、`768 × 1024`、`768*1024` 都认,交回 `768x1024`;认不出、或有一边比下限小,回 null。
 *  和后端 operations._check_custom_size 同一个判据。 */
export function parseCustomSize(text: string, minimum = 1): string | null {
  const found = /^\s*(\d+)\s*[x×*]\s*(\d+)\s*$/i.exec(text);
  if (!found) return null;
  const width = Number(found[1]);
  const height = Number(found[2]);
  return Math.min(width, height) >= minimum ? `${width}x${height}` : null;
}

export function videoResolutionOptions(model: GenerationOption | null): string[] {
  if (!supportsParameter(model, "resolution")) return [];
  return capabilityList(model, "resolutions", UNDECLARED);
}

export function aspectRatioOptions(model: GenerationOption | null): string[] {
  if (!supportsParameter(model, "aspect_ratio")) return [];
  return capabilityList(model, "aspect_ratios", UNDECLARED);
}

/**
 * 时长的**可选档位**。空数组有三种含义,都不该被编成一个值:
 *
 * - 模型不支持时长 → 空(上面那行);
 * - 支持,但它是个**区间**而不是几个档 → 也是空,由 min/max 说了算(见 durationRange);
 * - 支持,但目录里根本没有这个模型 → 还是空,由界面渲染成自由输入(见 ADR 0015)。
 *
 * 所以这里不能走 capabilityNumberList 的兜底 —— 那个兜底把空数组当成"没声明"、回落到
 * `[5]`,于是区间型的模型永远显示成一个只有 5 的下拉。Seedance 2 收 4–15 秒,而界面
 * 只给一个选项,正是这么来的。
 *
 * **第三种是后来才补上的。** 此前字段完全缺席时这里也回 `[5]`,那个 5 会被选中并提交 ——
 * 用户没选过时长,成片却是 5 秒。量过:39 份内置档案里没有一份是"声明了键却完全没有这个
 * 字段"的(区间型给的是空数组),所以这一支只在**未知模型**上开火,也就是最不该编值的那种。
 */
export function durationOptions(model: GenerationOption | null): number[] {
  if (!supportsParameter(model, "duration_seconds")) return [];
  const value = model?.capabilities?.duration_seconds;
  if (!Array.isArray(value)) return [];
  return value.map((item) => Number(item)).filter((item) => Number.isFinite(item) && item > 0);
}

/** 区间以外的合法时长值，例如 Seedance 2.5 的 -1=自动。 */
export function durationSpecialValues(model: GenerationOption | null): number[] {
  if (!supportsParameter(model, "duration_seconds")) return [];
  const value = model?.capabilities?.duration_special_values;
  if (!Array.isArray(value)) return [];
  return value.map(Number).filter(Number.isFinite);
}

/** 时长是区间时的上下界;不是区间(或没声明上界)时返回 null。 */
export function durationRange(model: GenerationOption | null): { min: number; max: number } | null {
  if (durationOptions(model).length > 0) return null;
  const max = capabilityNumber(model, "max_duration_seconds", 0);
  if (max <= 0) return null;
  return { min: capabilityNumber(model, "min_duration_seconds", 1) || 1, max };
}

/** 所有可在 UI 中选择的时长值：特殊值、离散档位或完整整数区间。 */
export function durationChoices(model: GenerationOption | null, resolution = ""): number[] {
  const special = durationSpecialValues(model);
  const discrete = durationOptions(model);
  const range = durationRange(model);
  const regular = discrete.length > 0
    ? discrete
    : range
      ? Array.from({ length: Math.floor(range.max) - Math.ceil(range.min) + 1 }, (_, index) => Math.ceil(range.min) + index)
      : [];
  const byResolution = model?.capabilities?.duration_by_resolution;
  const constrained = byResolution && typeof byResolution === "object"
    ? (byResolution as Record<string, unknown>)[resolution]
    : undefined;
  const allowed = Array.isArray(constrained)
    ? constrained.map(Number).filter((item) => Number.isFinite(item) && item > 0)
    : regular;
  return [...new Set([...special, ...allowed])];
}

/** 默认时长允许是 -1；通用 capabilityNumber 有意只接收正数，不适合这里。
 *
 *  **没有任何声明时回 0 = 未设置**,不再编一个 5。编出来的那个 5 会被原样提交 ——
 *  用户没选过时长,成片却是 5 秒(见 ADR 0015 与 catalog.fallback_capabilities)。 */
export const DURATION_UNSET = 0;

export function defaultDuration(model: GenerationOption | null, fallback = DURATION_UNSET): number {
  const declared = Number(model?.capabilities?.default_duration_seconds);
  if (Number.isFinite(declared)) return declared;
  return durationChoices(model)[0] ?? fallback;
}

/** 工作流字符串表单写回类型化参数，避免 "false" 在 Python 中被 bool("false") 判成 true。 */
export function parseGenerationParameterInput(value: string): string | number | boolean {
  if (value === "true") return true;
  if (value === "false") return false;
  return /^-?\d+(\.\d+)?$/.test(value) ? Number(value) : value;
}

export function maxImages(model: GenerationOption | null): number {
  return capabilityNumber(model, "max_num_images", 4);
}

function positiveInteger(value: unknown): number | undefined {
  return typeof value === "number" && Number.isInteger(value) && value >= 1 ? value : undefined;
}

/**
 * 张数为 1 时**一次交回几份**:模型说的 `outputs_per_run`(ComfyUI 的一张工作流跑一遍交回几张:几个结果节点各收到
 * 它那批),某个参数的取值改变它时(「结果取自」只要其中一个节点的)按那个参数的 `x-outputs-per-run`。和后端
 * generation.catalog.outputs_per_run 同一个算法 —— 画板按它 × 张数一次摆好那么多格占位,「N×」上显示的就是那个总数。
 */
export function outputsPerRun(model: GenerationOption | null, parameters: Record<string, unknown>): number {
  let perRun = positiveInteger(model?.capabilities?.outputs_per_run) ?? 1;
  const schema = model?.capabilities?.parameter_schema;
  if (schema && typeof schema === "object") {
    for (const [key, spec] of Object.entries(schema as Record<string, unknown>)) {
      const table = spec && typeof spec === "object" ? (spec as Record<string, unknown>)["x-outputs-per-run"] : undefined;
      if (!table || typeof table !== "object" || !(key in parameters)) continue;
      perRun = positiveInteger((table as Record<string, unknown>)[String(parameters[key])]) ?? perRun;
    }
  }
  return perRun;
}

/**
 * 这个模型的「张数」数的是**跑几遍**(ComfyUI 的工作流,描述符的 `num_images_unit: "runs"`):每遍按工作流原样出它
 * 那一批(画布上存着的批量照旧),一共是跑几遍 × 一遍几张。别的模型的张数就是张数。
 */
export function countsRuns(model: GenerationOption | null): boolean {
  return model?.capabilities?.num_images_unit === "runs";
}

/**
 * 跑几遍那一格下面的说明:每遍出几张(批量 × 几个结果节点)、这次一共几张。一遍每个结果节点出几张判不出来
 * (`batch_per_run` 没给)时不报数,只说「一遍出几张由工作流定」—— 宁可不说,不说错。
 */
export function runsHint(
  t: (key: MessageKey) => string,
  model: GenerationOption | null,
  parameters: Record<string, unknown>,
  runs: number,
): string {
  const perRun = outputsPerRun(model, parameters);
  const batch = positiveInteger(model?.capabilities?.batch_per_run);
  if (!batch || perRun % batch !== 0) return t("genRunsHintUnknown").replace("{runs}", String(runs));
  const nodes = perRun / batch;
  const detail = batch > 1 && nodes > 1 ? "genRunsDetailBatchNodes" : batch > 1 ? "genRunsDetailBatch" : nodes > 1 ? "genRunsDetailNodes" : null;
  const head = (detail ? t("genRunsHint").replace("{detail}", t(detail)) : t("genRunsHintPlain"))
    .replace("{batch}", String(batch))
    .replace("{nodes}", String(nodes));
  return head.replace("{perRun}", String(perRun)).replace("{total}", String(perRun * runs));
}

/**
 * 换模型时参数里**留下哪几项**:新模型仍收的键里,`{{…}}` 绑定原样留着(值要到运行时才知道,能不能收由
 * 运行前检查按新模型判),写死的值只在新模型的可选值里还有它时才留 —— 不在的(Veo 不收 5 秒)丢掉,
 * 交给新模型的默认。
 *
 * 此前换模型一律清空:官方模板按开始参数接好的画幅 / 尺寸 / 分辨率绑定(`{{input.aspect_ratio}}`)
 * 一换模型全没了,改开始节点的画幅从此不起作用,出来的片子按新模型的默认画幅。
 */
export function carriedParameters(
  previous: Record<string, unknown>,
  model: GenerationOption | null,
): Record<string, unknown> {
  const resolution = typeof previous.resolution === "string" ? previous.resolution : "";
  const choicesFor = (key: string): string[] | null => {
    if (key === "aspect_ratio") return aspectRatioOptions(model);
    if (key === "size") return sizeOptions(model);
    if (key === "resolution") return videoResolutionOptions(model);
    if (key === "duration_seconds") return durationChoices(model, resolution).map(String);
    const declared = parameterChoiceEntries(model).find(([name]) => name === key);
    return declared ? declared[1] : null;
  };
  const kept: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(previous)) {
    if (!supportsParameter(model, key)) continue;
    if (typeof value === "string" && value.includes("{{")) {
      kept[key] = value;
      continue;
    }
    const choices = choicesFor(key);
    if (choices && choices.length > 0 && !choices.includes(String(value))) continue;
    kept[key] = value;
  }
  return kept;
}
