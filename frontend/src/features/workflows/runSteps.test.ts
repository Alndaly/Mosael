import { describe, expect, it } from "vitest";

import type { TaskEvent } from "@/api/client";
import { toSteps } from "@/features/workflows/runSteps";

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
      },
    ]);
  });
});
