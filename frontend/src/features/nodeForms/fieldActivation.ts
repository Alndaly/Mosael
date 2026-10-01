/**
 * 配置字段是否参与当前节点。
 *
 * 条件来自后端节点注册表。表单、就绪检查和动态选项请求都读同一条声明，避免每种节点在
 * 前端各写一段 `if (node.type === ...)`。值没填(缺失、null、空串)时读取父字段声明的 default。两端语义由
 * `contracts/workflow-field-activation.json` 共同校验。
 */
export interface ActivatableFieldSpec {
  default?: unknown;
  active_when?: Record<string, unknown | unknown[]>;
  /** 同组的字段恰好填一个(值是组名,后端 NODE_TYPES 的 `one_of`)。 */
  one_of?: string;
}

export function isWorkflowFieldActive(
  spec: ActivatableFieldSpec | null | undefined,
  config: Record<string, unknown>,
  specs: Record<string, ActivatableFieldSpec | null | undefined>,
): boolean {
  const conditions = spec?.active_when;
  if (!conditions) return true;
  return Object.entries(conditions).every(([key, expected]) => {
    // 「没填」= 键不在、null、空串 —— 和后端、执行体同一个意思(执行体按 `值 or 缺省` 读)。
    const saved = config[key];
    const actual = saved === undefined || saved === null || saved === "" ? specs[key]?.default : saved;
    if (typeof actual === "string" && actual.includes("{{")) return true;
    return Array.isArray(expected) ? expected.includes(actual) : actual === expected;
  });
}

/** 声明了 `one_of` 的字段按组名归拢,顺序是声明的顺序。 */
export function oneOfGroups(specs: Record<string, ActivatableFieldSpec | null | undefined>): string[][] {
  const groups = new Map<string, string[]>();
  for (const [key, spec] of Object.entries(specs)) {
    if (spec?.one_of) groups.set(spec.one_of, [...(groups.get(spec.one_of) ?? []), key]);
  }
  return [...groups.values()];
}

/** 整格就是一条引用(`{{上游.输出}}`),没有别的字:运行时它的值全看上游,可能是空的。 */
export function isPureReference(value: unknown): boolean {
  return typeof value === "string" && /^\s*\{\{\s*[\w.-]+\s*\}\}\s*$/.test(value);
}

/**
 * 同组(`one_of`)填了的那几格(按声明顺序)算不算「填了不止一个」。
 *
 * 运行时按声明顺序取**第一个非空值**(与后端 graph_rules._one_of_errors 同一条)。所以前面填了的
 * 都只是一条引用、或接了数据边时,它们在运行时可能是空的 —— 最后那格是兜底,不是冲突:点击节点的
 * 选择器接上游、文字写死一个按钮名,上游没给选择器就按文字点。前面有一格是字面量(或引用里夹着别的字)
 * 才是真的两个都填了,运行时后面那格永远用不上。
 */
export function oneOfOverfilled(
  filled: readonly string[],
  config: Record<string, unknown>,
  isBound: (key: string) => boolean = () => false,
): boolean {
  if (filled.length < 2) return false;
  return !filled.slice(0, -1).every((key) => isBound(key) || isPureReference(config[key]));
}

/**
 * 同组(`one_of`)里别的字段已经填了、这一格还空着:表单把它收起来,从源头上填不出两个。
 *
 * 两格都已经填了(改规矩之前存下的节点)就**都留着** —— 藏起来的话人既看不见也清不掉;
 * 就绪检查会把它报出来。接了上游(`isBound`)也算填了。
 */
export function isTakenByOneOfPeer(
  key: string,
  specs: Record<string, ActivatableFieldSpec | null | undefined>,
  config: Record<string, unknown>,
  isBound: (key: string) => boolean = () => false,
): boolean {
  const group = oneOfGroups(specs).find((keys) => keys.includes(key));
  if (!group) return false;
  const filled = (one: string) => isBound(one) || String(config[one] ?? "").trim() !== "";
  return !filled(key) && group.some((one) => one !== key && filled(one));
}
