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
