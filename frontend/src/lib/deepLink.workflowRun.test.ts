import { describe, expect, it } from "vitest";

import { parseWorkflowRunLink, workflowRunLink } from "@/lib/deepLink";

describe("打开某一次运行的载荷", () => {
  it("工作流 id 和运行 id 来回不走样", () => {
    expect(parseWorkflowRunLink(workflowRunLink("wf1", "job9"))).toEqual({ workflowId: "wf1", runId: "job9" });
  });

  it.each(["", "wf1", "wf1/", "/job9", "a/b/c"])("认不出的 %j 不当成一次运行", (link) => {
    expect(parseWorkflowRunLink(link)).toBeNull();
  });
});
