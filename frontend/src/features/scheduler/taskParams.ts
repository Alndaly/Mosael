/**
 * 定时任务带给工作流的那一份参数(`payload.params`)。
 *
 * 到点跑工作流时,这份参数叠在**开始节点**的参数上(后端 graph_rules.with_run_params,和点运行同一套校验);开始节点里
 * 勾了「必填」又没有默认值的那几项,任务这边不给就跑不起来。此前新建任务的弹窗没有地方填,参数写死成 `{}`,
 * 只要工作流有一个必填输入就建不成(体检 UM-03)。
 *
 * 只认开始节点的参数:别的节点要填的东西(选一份素材、一条连接)不归任务给,得先在工作流里填好。
 */

export interface StartParamOption {
  value: string;
  label?: string;
}

export interface StartParamSpec {
  name: string;
  /** 开始节点里写的默认值;任务不给这一项时用它。 */
  fallback: unknown;
  required: boolean;
  options?: StartParamOption[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

/** 一张工作流图的开始节点声明了哪些参数(按声明的顺序)。没有开始节点就是空的。 */
export function startParamsOf(graph: unknown): StartParamSpec[] {
  const nodes = isRecord(graph) && Array.isArray(graph.nodes) ? graph.nodes : [];
  const start = nodes.find((node) => isRecord(node) && node.type === "start");
  const config = isRecord(start) && isRecord(start.config) ? start.config : {};
  const params = isRecord(config.params) ? config.params : {};
  const required = new Set(Array.isArray(config.required_params) ? config.required_params.filter((one) => typeof one === "string") : []);
  const declared = isRecord(config.param_options) ? config.param_options : {};
  return Object.entries(params).map(([name, fallback]) => {
    const list = declared[name];
    const options = Array.isArray(list)
      ? list.filter(isRecord).map((one) => ({ value: String(one.value ?? ""), label: typeof one.label === "string" ? one.label : undefined }))
      : undefined;
    return { name, fallback, required: required.has(name), options: options && options.length > 0 ? options : undefined };
  });
}

function blank(value: unknown): boolean {
  return value === undefined || value === null || (typeof value === "string" && value.trim() === "");
}

/** 表单里每一格显示什么:任务里存过的值;没存过就空着(占位里写默认值)。 */
export function formValuesFrom(specs: StartParamSpec[], saved: unknown): Record<string, string> {
  const params = isRecord(saved) ? saved : {};
  return Object.fromEntries(specs.map((spec) => [spec.name, blank(params[spec.name]) ? "" : String(params[spec.name])]));
}

/** 必填、表单里空着、开始节点也没有默认值 —— 这几项不填就跑不起来。 */
export function missingRequired(specs: StartParamSpec[], values: Record<string, string>): string[] {
  return specs.filter((spec) => spec.required && blank(values[spec.name]) && blank(spec.fallback)).map((spec) => spec.name);
}

/**
 * 要存进任务的参数:只存填了的那几格。空着的不存 —— 那一项跟着工作流里的默认值走,以后改默认值任务也跟着变。
 * 默认值是数字的那一项,填的是数字就存成数字(开始节点里的 `scene_count: 4` 不该变成字符串 `"4"`)。
 */
export function runParamsFrom(specs: StartParamSpec[], values: Record<string, string>): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  for (const spec of specs) {
    const raw = values[spec.name];
    if (blank(raw)) continue;
    const text = raw.trim();
    params[spec.name] = typeof spec.fallback === "number" && text !== "" && Number.isFinite(Number(text)) ? Number(text) : text;
  }
  return params;
}
