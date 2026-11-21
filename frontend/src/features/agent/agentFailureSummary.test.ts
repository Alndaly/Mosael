import { expect, it } from "vitest";

import { agentFailureSummary } from "./agentFailureSummary";

it("优先使用后端给人的失败说法,不拿半截正文当原因", () => {
  expect(agentFailureSummary({
    content: "我先读一下技能，再读画布和做诊断。",
    payload: { failure_text: "与模型服务的连接中断了，请重试。" },
  })).toBe("与模型服务的连接中断了，请重试。");
});

it("没有失败说法时才退回正文", () => {
  expect(agentFailureSummary({ content: "执行失败", payload: null })).toBe("执行失败");
});
