/**
 * 配置字段是否参与当前节点。
 *
 * 条件来自后端节点注册表。表单、就绪检查和动态选项请求都读同一条声明，避免每种节点在
 * 前端各写一段 `if (node.type === ...)`。值缺失时也会读取父字段声明的 default。两端语义由
 * `contracts/workflow-field-activation.json` 共同校验。
 */
export interface ActivatableFieldSpec {
  default?: unknown;
  active_when?: Record<string, unknown | unknown[]>;
}

export function isWorkflowFieldActive(
  spec: ActivatableFieldSpec | null | undefined,
  config: Record<string, unknown>,
  specs: Record<string, ActivatableFieldSpec | null | undefined>,
): boolean {
  const conditions = spec?.active_when;
  if (!conditions) return true;
  return Object.entries(conditions).every(([key, expected]) => {
    const actual = config[key] ?? specs[key]?.default;
    if (typeof actual === "string" && actual.includes("{{")) return true;
    return Array.isArray(expected) ? expected.includes(actual) : actual === expected;
  });
}
