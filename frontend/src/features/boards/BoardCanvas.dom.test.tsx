/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN", t: (key: string) => key }),
}));

import type { BoardCanvas as Canvas } from "@/api/client";
import { ImagePreviewProvider } from "@/components/app/image-preview";
import { BoardCanvas, type BoardCanvasApi } from "@/features/boards/BoardCanvas";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
});

afterEach(() => {
  vi.useRealTimers();
});

function mount(canvas: Canvas) {
  let api: BoardCanvasApi | null = null;
  const changes: Canvas[] = [];
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ImagePreviewProvider>
      <div style={{ width: 800, height: 600 }}>
        <BoardCanvas
          boardId="b1"
          workspaceId="w1"
          canvas={canvas}
          onChange={(next) => changes.push(next)}
          onPickAsset={() => undefined}
          onReady={(next) => {
            api = next;
          }}
        />
      </div>
      </ImagePreviewProvider>
    </QueryClientProvider>,
  );
  return { api: () => api as unknown as BoardCanvasApi, latest: () => changes[changes.length - 1] };
}

const note = (id: string, text: string) => ({ id, kind: "note" as const, x: 0, y: 0, width: 220, height: 140, color: "yellow" as const, text });

describe("画板的撤销与服务端那份", () => {
  it("冲突后换成服务端那份,撤销不会把别人刚做的改动一起撤掉", async () => {
    const view = mount({ items: [note("n1", "")], edges: [], markers: [] });
    // 本地写了一句,攒够一步进历史。
    act(() => view.api().patch("n1", { text: "我写的" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(view.api().canUndo).toBe(true);

    // 保存撞了冲突:别处(智能体)刚在板上加了一张便签,本地换成服务端那份。
    const server: Canvas = { items: [note("n1", "我写的"), note("agent", "智能体加的")], edges: [], markers: [] };
    act(() => view.api().replace(server));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });

    act(() => view.api().undo());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });

    expect(view.latest().items.map((one) => one.id)).toContain("agent");
  });
});

describe("上游断开之后,下游表单里那份引用跟着摘掉", () => {
  const upstream = { id: "A", kind: "image" as const, x: 0, y: 0, width: 260, height: 180, asset_id: "a1" };
  const manual = { asset_id: "m1", role: "last_frame" };
  const downstream = {
    id: "V",
    kind: "video" as const,
    x: 400,
    y: 0,
    width: 320,
    height: 200,
    form: { prompt: "动起来", source_assets: [{ asset_id: "a1", role: "first_frame" }, manual] },
  };
  const board: Canvas = { items: [upstream, downstream], edges: [{ id: "e1", source: "A", target: "V" }], markers: [] };

  it("上游那张换成另一份素材:下游挂着的旧那份不再发出去,手动挂的照留", async () => {
    const view = mount(board);

    act(() => view.api().patch("A", { asset_id: "b1" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });

    const video = view.latest().items.find((one) => one.id === "V")!;
    expect(video.form?.source_assets).toEqual([manual]);
  });

  it("上游那一格删掉:下游挂着的那份不再发出去,手动挂的照留", async () => {
    const view = mount(board);

    const node = document.querySelector('[data-id="A"]') as HTMLElement;
    act(() => {
      node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    act(() => {
      document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "Delete", bubbles: true }));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });

    const items = view.latest().items;
    expect(items.map((one) => one.id)).toEqual(["V"]);
    expect(items[0].form?.source_assets).toEqual([manual]);
  });
});
