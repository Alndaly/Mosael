/**
 * 开始节点选项参数「值不在选项里」的画布一侧:跑 contracts/workflow-start-option-cases.json。
 *
 * 后端运行前按 graph_rules.start_option_violations 拦(backend/tests/test_workflow_start_option_parity.py 跑同一份语料)。
 */
import { describe, expect, it } from "vitest";

import contract from "../../../../contracts/workflow-start-option-cases.json";

import { startOptionViolations } from "@/features/workflows/analyze";

describe("选项参数的值不在选项里(契约)", () => {
  it.each(contract.cases)("$name", ({ config, violations }) => {
    expect(startOptionViolations(config as Record<string, unknown>)).toEqual(violations);
  });
});
