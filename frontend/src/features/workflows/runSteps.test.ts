import { describe, expect, it } from "vitest";

import type { TaskEvent } from "@/api/client";
import { toSteps } from "@/features/workflows/runSteps";

describe("节点自己报的进度", () => {
  const event = (id: string, type: string, at: string, payload: Record<string, unknown>) =>
    ({ id, job_id: "j1", type, created_at: at, payload }) as TaskEvent;

  it("跑着的节点带上最新的一句;跑完之后迟到的进度不再改它", () => {
    const running = [
      event("e1", "workflow.node.started", "2026-09-25T08:00:00Z", { node_id: "n1", name: "放大" }),
      event("e2", "workflow.node.progress", "2026-09-25T08:00:01Z", { node_id: "n1", progress: 0.2, message: "采样 4/20" }),
      event("e3", "workflow.node.progress", "2026-09-25T08:00:02Z", { node_id: "n1", progress: 0.5, message: "采样 10/20" }),
    ];
    const [step] = toSteps(running);
    expect(step.status).toBe("running");
    expect(step.message).toBe("采样 10/20");
    expect(step.progress).toBe(0.5);

    const finished = toSteps([
      ...running,
      event("e4", "workflow.node.finished", "2026-09-25T08:00:03Z", { node_id: "n1", outputs: {} }),
      event("e5", "workflow.node.progress", "2026-09-25T08:00:04Z", { node_id: "n1", progress: 0.9, message: "迟到的一句" }),
    ]);
    expect(finished[0].status).toBe("done");
    expect(finished[0].message).toBe("采样 10/20");
  });

  it("跑完的那一步带着截断说明和它属于哪一次运行 —— 全文按这两样去取", () => {
    const [step] = toSteps([
      event("e1", "workflow.node.started", "2026-09-25T08:00:00Z", { node_id: "n1", name: "写稿" }),
      event("e2", "workflow.node.finished", "2026-09-25T08:00:03Z", { node_id: "n1", outputs: { text: "开头…" }, truncated: { text: 3200 } }),
    ]);
    expect(step.truncated).toEqual({ text: 3200 });
    expect(step.jobId).toBe("j1");
  });
});

describe("工作流失败步骤", () => {
  it("保留任务事件里的结构化失败现场", () => {
    const events = [
      {
        id: "e1",
        job_id: "j1",
        type: "workflow.node.started",
        created_at: "2026-09-04T08:00:00Z",
        payload: { node_id: "llm", name: "整理方案" },
      },
      {
        id: "e2",
        job_id: "j1",
        type: "workflow.node.failed",
        created_at: "2026-09-04T08:00:01Z",
        payload: {
          node_id: "llm",
          name: "整理方案",
          error: "LLM 未返回合法 JSON",
          details: { raw_response: "not json", response_format: "json_object" },
        },
      },
    ] as TaskEvent[];

    expect(toSteps(events)).toEqual([
      {
        nid: "llm",
        name: "整理方案",
        status: "failed",
        startAt: Date.parse("2026-09-04T08:00:00Z"),
        ms: 1000,
        error: "LLM 未返回合法 JSON",
        //: 给人看的那几样(那一句、原文、原因和怎么修):事件上没有后端摘好的,就是原文本身
        failure: { summary: "LLM 未返回合法 JSON", detail: null, fix: null, copyText: "LLM 未返回合法 JSON" },
        details: { raw_response: "not json", response_format: "json_object" },
      },
    ]);
  });

  it("旧记录即使缺少 started 事件也保留已完成步骤", () => {
    const events = [
      {
        id: "e1",
        job_id: "j1",
        type: "workflow.node.finished",
        created_at: "2026-09-04T08:00:01Z",
        payload: { node_id: "copy", name: "复制原视频", outputs: { sequence_id: "s1" } },
      },
    ] as TaskEvent[];

    expect(toSteps(events)).toEqual([
      {
        nid: "copy",
        name: "复制原视频",
        status: "done",
        outputs: { sequence_id: "s1" },
        jobId: "j1",
      },
    ]);
  });

  it("总任务因后端重启中断时收口仍在运行的节点", () => {
    const events = [
      {
        id: "e1",
        job_id: "j1",
        type: "workflow.node.started",
        created_at: "2026-09-19T04:00:00Z",
        payload: { node_id: "translate", name: "逐句翻译" },
      },
      {
        id: "e2",
        job_id: "j1",
        type: "job.failed",
        created_at: "2026-09-19T04:01:30Z",
        payload: { reason: "backend_restart" },
      },
    ] as TaskEvent[];

    expect(toSteps(events)).toEqual([
      {
        nid: "translate",
        name: "逐句翻译",
        status: "failed",
        startAt: Date.parse("2026-09-19T04:00:00Z"),
        ms: 90_000,
      },
    ]);
  });

  //: 点了停止的那一次,在跑的那一步是被停下的,不是出错:画布和历史按「已取消」说,不标红。
  it.each(["workflow.cancelled", "job.cancelled"])("总任务被取消(%s):在跑的那一步收口成已取消,不是失败", (type) => {
    const events = [
      { id: "e1", job_id: "j1", type: "workflow.node.started", created_at: "2026-09-19T04:00:00Z", payload: { node_id: "a", name: "上一步" } },
      { id: "e2", job_id: "j1", type: "workflow.node.finished", created_at: "2026-09-19T04:00:05Z", payload: { node_id: "a", outputs: {} } },
      { id: "e3", job_id: "j1", type: "workflow.node.started", created_at: "2026-09-19T04:00:05Z", payload: { node_id: "b", name: "生成" } },
      { id: "e4", job_id: "j1", type, created_at: "2026-09-19T04:00:15Z", payload: {} },
    ] as TaskEvent[];

    const steps = toSteps(events);
    expect(steps.map((step) => step.status)).toEqual(["done", "cancelled"]);
    expect(steps[1].ms).toBe(10_000);
  });
});
