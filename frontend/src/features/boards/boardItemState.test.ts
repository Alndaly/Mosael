import { describe, expect, it } from "vitest";

import type { BoardItem } from "@/api/client";
import { boardSettlementPatch, composerFor, itemFormResetKey, itemIsRunning, itemRunStatus } from "./boardItemState";

function image(extra: Partial<BoardItem> = {}): BoardItem {
  return { id: "image-1", kind: "image", x: 0, y: 0, ...extra };
}

describe("画布节点状态", () => {
  it("没有运行态时为空闲", () => {
    expect(itemRunStatus(image())).toBe("idle");
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

describe("终态轮询补丁", () => {
  it("成功时同步服务端清空后的表单，而不是只换 asset_id", () => {
    const item = image({
      asset_id: "asset-1",
      form: { prompt: "", provider: "evolink", model: "m", source_assets: [], mentioned_asset_ids: [] },
      run: { status: "succeeded" },
    });
    expect(boardSettlementPatch(item)).toMatchObject({ asset_id: "asset-1", form: item.form });
  });

  it("按状态认「跑完了」:没留下原因的失败、被取消,同样落回画布", () => {
    // 服务端不再拿状态名顶替原因 —— 原因可以没有,那一格照样要停下转圈。
    expect(boardSettlementPatch(image({ run: { status: "failed" } }))).toEqual({ run: { status: "failed" } });
    expect(boardSettlementPatch(image({ run: { status: "cancelled" } }))).toEqual({ run: { status: "cancelled" } });
  });

  it("还在跑的那一格不出补丁", () => {
    expect(boardSettlementPatch(image({ run: { status: "running", job_id: "job-1" } }))).toBeNull();
  });
});

describe("选中一格时挂哪块面板", () => {
  const trim = { asset_id: "src", start: 1, end: 3, mute: false };

  it("截挂了的那一格挂截取面板,不是生成/念的面板", () => {
    expect(composerFor({ id: "v", kind: "video", x: 0, y: 0, form: { trim }, run: { status: "failed", error: "截取失败" } })).toBe("trim");
    expect(composerFor({ id: "a", kind: "audio", x: 0, y: 0, form: { trim }, run: { status: "failed" } })).toBe("trim");
  });

  it("其余没有产出的按种类:图片视频生成、音频念、便签写", () => {
    expect(composerFor(image({ run: { status: "failed", error: "上游失败" } }))).toBe("generate");
    expect(composerFor({ id: "a", kind: "audio", x: 0, y: 0 })).toBe("speak");
    expect(composerFor({ id: "n", kind: "note", x: 0, y: 0, text: "有字" })).toBe("write");
  });

  it("有了产出的、分组框这类不挂", () => {
    expect(composerFor(image({ asset_id: "a1", form: { trim } }))).toBeNull();
    expect(composerFor({ id: "f", kind: "frame", x: 0, y: 0 })).toBeNull();
  });
});
