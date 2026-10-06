import { describe, expect, it } from "vitest";

import { summarizeMessageUsage, type AgentUsageEvent } from "./messageUsage";

const event = (overrides: Partial<AgentUsageEvent>): AgentUsageEvent => ({
  id: "e",
  agent_message_id: "m",
  provider: "alibaba",
  model: "qwen-image",
  capability: "image",
  operation: "generation_job",
  status: "succeeded",
  duration_seconds: null,
  units: {},
  cost_micros: null,
  currency: "USD",
  cost_confidence: "unknown",
  ...overrides,
});

describe("一条消息的花费:没花的钱不是钱", () => {
  //: 失败了服务商什么都没回(not_billed)、免费的引擎(free)都记 0;没定价的模型那笔 0 的币种是猜的美元 ——
  //: 当成一笔钱就是「费用 US$0.00」。和后端汇总(billing.usage.NOT_SPENT)同一个口径。
  it("没扣钱的、免费的不进金额;没扣钱的单独数,说「未扣费」用", () => {
    const summary = summarizeMessageUsage([
      event({ id: "a", status: "failed", cost_micros: 0, cost_confidence: "not_billed" }),
      event({ id: "b", cost_micros: 0, cost_confidence: "free" }),
    ]);
    expect(summary.costs).toEqual([]);
    expect(summary.notBilledEvents).toBe(1);
    expect(summary.unknownCostEvents).toBe(0);
  });

  it("花了钱的照币种各一笔;没价的照旧数成「未定价」", () => {
    const summary = summarizeMessageUsage([
      event({ id: "a", cost_micros: 250_000, currency: "CNY", cost_confidence: "estimated" }),
      event({ id: "b", status: "failed", cost_micros: 0, currency: "CNY", cost_confidence: "not_billed" }),
      event({ id: "c" }),
    ]);
    expect(summary.costs).toEqual([{ currency: "CNY", micros: 250_000 }]);
    expect(summary.unknownCostEvents).toBe(1);
  });
});
