/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render } from "@testing-library/react";
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

function mount(canvas: Canvas, extra: Partial<React.ComponentProps<typeof BoardCanvas>> = {}) {
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
          {...extra}
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

describe("给一格改名", () => {
  const image = (id: string, title?: string) => ({ id, kind: "image" as const, x: 0, y: 0, width: 260, height: 180, ...(title ? { title } : {}) });

  async function settle() {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
  }

  it("操作条上的「重命名」打开名字那一处;打完一个名字是撤销历史里的一步", async () => {
    const view = mount({ items: [image("a"), image("b", "侧面")], edges: [], markers: [] });
    const node = document.querySelector('[data-id="a"]') as HTMLElement;
    act(() => {
      node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await settle();
    expect(view.api().canUndo).toBe(false);

    const rename = document.querySelector<HTMLButtonElement>('.react-flow__node-toolbar button[aria-label="rename"]');
    expect(rename, "单选一格时操作条上有「重命名」").not.toBeNull();
    act(() => rename!.click());
    const input = node.querySelector<HTMLInputElement>('input[aria-label="rename"]')!;
    expect(input, "输入框开在这一格上方的名字那一处").not.toBeNull();

    //: 一个字一个字地打:每一下都只进草稿,不进画布 —— 否则攒不成一步。
    for (const value of ["正", "正面", "正面特写"]) {
      fireEvent.change(input, { target: { value } });
      await settle();
    }
    expect(view.latest().items.find((one) => one.id === "a")?.title).toBeUndefined();
    expect(view.api().canUndo).toBe(false);

    fireEvent.keyDown(input, { key: "Enter" });
    await settle();
    expect(view.latest().items.map((one) => one.title)).toEqual(["正面特写", "侧面"]);
    expect(node.querySelector("[data-board-node-label]")?.textContent).toBe("正面特写");

    act(() => view.api().undo());
    await settle();
    expect(view.latest().items.map((one) => one.title)).toEqual([undefined, "侧面"]);
    expect(view.api().canUndo).toBe(false);
  });
});

describe("删除键只认冲着画布来的那一下", () => {
  //: 和工作流编辑器同一条规矩(lib/shortcuts 的 isCanvasKeyTarget):焦点停在面板里的按钮上、
  //: 或者在 Portal 到 body 的下拉选项上时按 Backspace,是冲着那个控件去的,不是删选中的那一格。
  const board: Canvas = { items: [note("n1", "留着"), note("n2", "也留着")], edges: [], markers: [] };

  function select(id: string) {
    const node = document.querySelector(`[data-id="${id}"]`) as HTMLElement;
    act(() => {
      node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
  }

  async function press(target: HTMLElement, key: string) {
    act(() => {
      target.focus();
      target.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
  }

  const ids = (view: ReturnType<typeof mount>) => view.latest()?.items.map((one) => one.id) ?? ["n1", "n2"];

  it("焦点在面板的按钮上:不删", async () => {
    const view = mount(board);
    select("n1");
    const button = document.querySelector<HTMLElement>(".react-flow__node-toolbar button");
    expect(button, "选中之后应该有浮在节点上的面板").not.toBeNull();
    await press(button!, "Backspace");
    expect(ids(view)).toEqual(["n1", "n2"]);
  });

  it("焦点在 Portal 出去的下拉选项上:不删", async () => {
    const view = mount(board);
    select("n1");
    const option = document.createElement("div");
    option.setAttribute("role", "option");
    option.tabIndex = -1;
    document.body.appendChild(option);
    await press(option, "Delete");
    option.remove();
    expect(ids(view)).toEqual(["n1", "n2"]);
  });

  it("焦点在画布上:照常删", async () => {
    const view = mount(board);
    select("n1");
    await press(document.querySelector<HTMLElement>('[data-id="n1"]')!, "Backspace");
    expect(view.latest().items.map((one) => one.id)).toEqual(["n2"]);
  });
});

describe("往画布上粘贴", () => {
  //: 粘贴冲着画布来才接(和删除键同一条判据,isCanvasKeyTarget):在输入框、编辑器里粘贴是往那儿贴字。
  function paste(target: HTMLElement, data: { text?: string; files?: File[] }) {
    const event = new Event("paste", { bubbles: true, cancelable: true });
    Object.defineProperty(event, "clipboardData", {
      value: { files: data.files ?? [], getData: (type: string) => (type === "text/plain" ? (data.text ?? "") : "") },
    });
    act(() => {
      target.focus();
      target.dispatchEvent(event);
    });
    return event;
  }

  async function settle() {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
  }

  it("一段文字落成一张便签", async () => {
    const view = mount({ items: [note("n1", "原来的")], edges: [], markers: [] });
    const event = paste(document.body, { text: "粘进来的想法" });
    await settle();
    expect(event.defaultPrevented).toBe(true);
    const added = view.latest().items.find((one) => one.id !== "n1");
    expect(added).toMatchObject({ kind: "note", text: "粘进来的想法", form: { producer: "write" } });
  });

  it("截图先进素材库,再按种类放一格", async () => {
    const onDropFiles = vi.fn(async (files: File[]) =>
      files.map((file, index) => ({ id: `a${index}`, name: file.name, kind: "image" as const })),
    );
    const view = mount({ items: [note("n1", "原来的")], edges: [], markers: [] }, { onDropFiles });
    paste(document.body, { files: [new File([new Uint8Array([1])], "", { type: "image/png" })], text: "<img>" });
    await settle();
    expect(onDropFiles).toHaveBeenCalledTimes(1);
    const added = view.latest().items.find((one) => one.id !== "n1");
    expect(added).toMatchObject({ kind: "image", asset_id: "a0" });
  });

  it("焦点在输入框里:不接,交给那个输入框", async () => {
    const view = mount({ items: [note("n1", "原来的")], edges: [], markers: [] });
    const input = document.createElement("textarea");
    document.querySelector(".react-flow")!.appendChild(input);
    const event = paste(input, { text: "打进输入框的字" });
    await settle();
    input.remove();
    expect(event.defaultPrevented).toBe(false);
    expect(view.latest()?.items.map((one) => one.id) ?? ["n1"]).toEqual(["n1"]);
  });
});

describe("截挂了的那一格,选中时挂的是截取面板", () => {
  it("范围原样在,重截落回这一格;不挂生成面板", async () => {
    const onRun = vi.fn(async () => undefined);
    const cut = {
      id: "cut",
      kind: "video" as const,
      x: 0,
      y: 0,
      width: 320,
      height: 200,
      form: { trim: { asset_id: "src", start: 1.5, end: 4, mute: true }, producer: "trim" as const },
      run: { status: "failed" as const, error: "截取失败" },
    };
    mount({ items: [cut], edges: [], markers: [] }, { onRun, models: [] });

    const node = document.querySelector('[data-id="cut"]') as HTMLElement;
    act(() => {
      node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });

    const start = document.querySelector('[aria-label="boardTrimStartLabel"]') as HTMLInputElement | null;
    expect(start?.value).toBe("1.5");
    expect(document.querySelector('[aria-label="boardTrimEndLabel"]')).toHaveProperty("value", "4");
    expect(document.querySelector('[title="boardDropSound"]')).not.toBeNull();

    const submit = [...document.querySelectorAll("button")].find((one) => one.textContent?.includes("boardTrimSubmit"));
    act(() => submit!.click());
    expect(onRun).toHaveBeenCalledTimes(1);
    expect(onRun).toHaveBeenCalledWith(expect.objectContaining({
      producer: "trim",
      item_id: "cut",
      form: { asset_id: "src", start: 1.5, end: 4, mute: true },
    }));
  });
});
