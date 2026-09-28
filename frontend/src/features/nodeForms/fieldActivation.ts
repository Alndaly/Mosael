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
