import { describe, expect, it, vi } from "vitest";

import type { Board, BoardItem } from "@/api/client";
import { runNoteWrite, type NoteWriteRun } from "./noteWriteLifecycle";

const run: NoteWriteRun = {
  producer: "write",
  item_id: "note-1",
  kind: "note",
  x: 0,
  y: 0,
  form: { prompt: "描述这张图片", provider_profile_id: "profile-1", model: "k3", source_assets: ["asset-1"], context: [] },
};

function board(item: BoardItem): Board {
  return {
    id: "board-1",
    workspace_id: "workspace-1",
    name: "画板",
    revision: 2,
    canvas: { items: [item], edges: [] },
    created_at: "",
    updated_at: "",
  };
}

describe("便签 AI 写作生命周期", () => {
  it("请求期间把 loading 写进节点，成功后清空一次性表单", async () => {
    let resolve!: (value: Board) => void;
    const request = vi.fn(
      () =>
        new Promise<Board>((done) => {
          resolve = done;
        }),
    );
    const patch = vi.fn<(itemId: string, next: Partial<BoardItem>) => void>();

    const pending = runNoteWrite({ run, request, patch });
    expect(patch).toHaveBeenNthCalledWith(1, "note-1", {
      run: { status: "running" },
    });

    resolve(
      board({
        id: "note-1",
        kind: "note",
        x: 0,
        y: 0,
        text: "晴朗草原上的女孩",
        form: {
          prompt: "",
          provider_profile_id: "profile-1",
          model: "k3",
          mentioned_asset_ids: [],
        },
        run: { status: "succeeded" },
      }),
    );
    await pending;

    expect(patch).toHaveBeenNthCalledWith(2, "note-1", {
      text: "晴朗草原上的女孩",
      form: {
        prompt: "",
        provider_profile_id: "profile-1",
        model: "k3",
        mentioned_asset_ids: [],
      },
      run: { status: "succeeded" },
    });
  });

  it("失败时节点结束 loading，但保留表单供重试", async () => {
    const patch = vi.fn<(itemId: string, next: Partial<BoardItem>) => void>();
    const failure = new Error("模型拒绝了请求");

    await expect(
      runNoteWrite({ run, request: () => Promise.reject(failure), patch }),
    ).rejects.toThrow("模型拒绝了请求");

    expect(patch).toHaveBeenLastCalledWith("note-1", {
      run: { status: "failed", error: "模型拒绝了请求" },
    });
    expect(patch.mock.calls.at(-1)?.[1]).not.toHaveProperty("form");
  });
});
