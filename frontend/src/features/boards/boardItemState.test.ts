import { describe, expect, it } from "vitest";

import type { BoardItem } from "@/api/client";
import { itemFormResetKey, itemIsRunning, itemRunStatus } from "./boardItemState";

function image(extra: Partial<BoardItem> = {}): BoardItem {
  return { id: "image-1", kind: "image", x: 0, y: 0, ...extra };
}

describe("画布节点状态", () => {
  it("旧节点也能恢复运行语义", () => {
    expect(itemRunStatus(image())).toBe("idle");
    expect(itemRunStatus(image({ job_id: "job-1" }))).toBe("running");
    expect(itemRunStatus(image({ error: "failed" }))).toBe("failed");
  });

  it("只有带 job id 的排队/运行节点才进入轮询", () => {
    expect(itemIsRunning(image({ run: { status: "running" } }))).toBe(false);
    expect(itemIsRunning(image({ run: { status: "queued", job_id: "job-1" } }))).toBe(true);
    expect(itemIsRunning(image({ run: { status: "succeeded" } }))).toBe(false);
  });

  it("拖动、编辑、运行和失败不重置表单局部状态", () => {
    const draft = image({ form: { prompt: "原提示词" } });
    const key = itemFormResetKey(draft);
    expect(itemFormResetKey({ ...draft, x: 320, y: 180 })).toBe(key);
    expect(itemFormResetKey({ ...draft, form: { prompt: "正在输入的新提示词" } })).toBe(key);
    expect(itemFormResetKey({ ...draft, run: { status: "running", job_id: "job-1" } })).toBe(key);
    expect(itemFormResetKey({ ...draft, run: { status: "failed", error: "上游失败" } })).toBe(key);
  });

  it("AI 成功或手动换素材时从节点表单重新水合", () => {
    const running = image({ run: { status: "running", job_id: "job-1" } });
    const succeeded = image({ asset_id: "asset-1", run: { status: "succeeded" } });
    const replaced = image({ asset_id: "asset-2", run: { status: "idle" } });
    expect(itemFormResetKey(succeeded)).not.toBe(itemFormResetKey(running));
    expect(itemFormResetKey(replaced)).not.toBe(itemFormResetKey(succeeded));
  });
});
