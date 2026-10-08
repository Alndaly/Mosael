import { describe, expect, it } from "vitest";

import { notificationRecord, OPEN_WORKFLOW_RUN, parseWorkflowRunLink, workflowRunLink } from "@/lib/deepLink";

describe("打开某一次运行的载荷", () => {
  it("工作流 id 和运行 id 来回不走样", () => {
    expect(parseWorkflowRunLink(workflowRunLink("wf1", "job9"))).toEqual({ workflowId: "wf1", runId: "job9" });
  });

  it.each(["", "wf1", "wf1/", "/job9", "a/b/c"])("认不出的 %j 不当成一次运行", (link) => {
    expect(parseWorkflowRunLink(link)).toBeNull();
  });
});

//: 体检 UM-17:「工作流失败」的通知此前只选中工作流、打开编辑器 —— 那次运行和失败原因都看不到。
describe("通知点进去打开哪一条", () => {
  it("工作流失败开的是那一次运行", () => {
    expect(notificationRecord("workflow", { workflow_id: "wf1", job_id: "job9" })).toEqual({
      event: OPEN_WORKFLOW_RUN,
      id: "wf1/job9",
    });
  });

  it("没带运行的工作流通知照旧打开工作流;发布打开那条发布;认不出的只跳页", () => {
    expect(notificationRecord("workflow", { workflow_id: "wf1" })).toEqual({ event: "mosael:open-workflow", id: "wf1" });
    expect(notificationRecord("publish", { task_id: "p1" })).toEqual({ event: "mosael:open-publish-task", id: "p1" });
    expect(notificationRecord("team", { invitation_id: "i1" })).toBeNull();
    expect(notificationRecord("workflow", null)).toBeNull();
  });
});
