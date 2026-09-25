/** @vitest-environment jsdom */
//: 便签 / 分组标题里用拼音打中文:组词期间 React 不许往框里写字,上屏后画布里是中文、
//: 自动保存只送一次上屏的那段。此前便签的字住在 React Flow 节点里(effect 里才抄进 store),
//: 每敲一个字母 React 都先把框写回旧字、再写新字 —— 组词被打断,字母直接上屏(「daa skx」)。
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN", t: (key: string) => key }),
}));

import type { BoardCanvas as Canvas, BoardItem } from "@/api/client";
import { ImagePreviewProvider } from "@/components/app/image-preview";
import { BoardCanvas, type BoardCanvasApi } from "@/features/boards/BoardCanvas";
import { useAutosave } from "@/lib/useAutosave";
import { composeWithIme, watchValueWrites } from "@/test/ime";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const note: BoardItem = { id: "n1", kind: "note", x: 0, y: 0, width: 220, height: 140, color: "yellow", text: "" };
const frame: BoardItem = { id: "f1", kind: "frame", x: 400, y: 0, width: 300, height: 200 };

/** 画布 + 真的自动保存(和 BoardsView 同一个钩子),记下每一次存了什么。 */
function mount(items: BoardItem[]) {
  const saved: Canvas[] = [];
  const emitted: Canvas[] = [];
  let api: BoardCanvasApi | null = null;
  function Harness() {
    const [canvas, setCanvas] = React.useState<Canvas | null>(null);
    useAutosave(canvas, (next) => {
      saved.push(next);
    });
    const onChange = React.useCallback((next: Canvas) => {
      emitted.push(next);
      setCanvas(next);
    }, []);
    return (
      <div style={{ width: 800, height: 600 }}>
        <BoardCanvas boardId="b1" workspaceId="w1" canvas={{ items, edges: [], markers: [] }} onChange={onChange} onPickAsset={() => undefined} onReady={(next) => (api = next)} />
      </div>
    );
  }
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ImagePreviewProvider>
        <Harness />
      </ImagePreviewProvider>
    </QueryClientProvider>,
  );
  const textOf = (canvas: Canvas | undefined, id: string) => canvas?.items.find((one) => one.id === id)?.text ?? "";
  return { saved, emitted, api: () => api as unknown as BoardCanvasApi, textOf };
}

async function settle(ms = 1000) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("便签里用拼音打中文", () => {
  it("组词期间框里的字不被改写;上屏后画布里是中文,自动保存只送一次", async () => {
    const view = mount([note]);
    await settle();
    const before = view.saved.length;

    act(() => {
      fireEvent.doubleClick(document.querySelector('[data-id="n1"] > div')!);
    });
    const box = document.querySelector<HTMLTextAreaElement>('[data-id="n1"] textarea')!;
    expect(box).not.toBeNull();
    const writes = watchValueWrites(box);

    const shortcut = vi.fn();
    window.addEventListener("keydown", shortcut);
    composeWithIme(box, ["n", "ni", "nih", "niha", "nihao"], "你好");
    window.removeEventListener("keydown", shortcut);

    //: 组词期间 React 一次都不该往框里写 —— 写一次,真机上的组词就断了。
    expect(writes).toEqual([]);
    expect(box.value).toBe("你好");
    expect(document.querySelector('[data-id="n1"] textarea')).toBe(box);
    await settle();

    expect(view.textOf(view.emitted.at(-1), "n1")).toBe("你好");
    //: 拼音字母不进画布(也就不进撤销历史、不被存下来)。
    expect(view.emitted.map((canvas) => view.textOf(canvas, "n1")).filter((text) => /[a-z]/i.test(text))).toEqual([]);
    const sent = view.saved.slice(before).map((canvas) => view.textOf(canvas, "n1"));
    expect(sent).toEqual(["你好"]);
  });

  it("接着已有的字往后打:前面的字留着,中文接在后面", async () => {
    const view = mount([{ ...note, text: "今天" }]);
    await settle();
    act(() => {
      fireEvent.doubleClick(document.querySelector('[data-id="n1"] > div')!);
    });
    const box = document.querySelector<HTMLTextAreaElement>('[data-id="n1"] textarea')!;
    const writes = watchValueWrites(box);
    composeWithIme(box, ["今天t", "今天ti", "今天tia", "今天tian", "今天tianq", "今天tianqi"], "今天天气");
    expect(writes).toEqual([]);
    await settle();
    expect(view.textOf(view.emitted.at(-1), "n1")).toBe("今天天气");
  });

  it("没在编辑时,外面改了字(撤销、服务端那份)照常显示", async () => {
    const view = mount([note]);
    await settle();
    act(() => view.api().patch("n1", { text: "智能体写的" }));
    await settle();
    expect(document.querySelector('[data-id="n1"]')?.textContent).toContain("智能体写的");
    act(() => {
      fireEvent.doubleClick(document.querySelector('[data-id="n1"] > div')!);
    });
    expect(document.querySelector<HTMLTextAreaElement>('[data-id="n1"] textarea')!.value).toBe("智能体写的");
  });
});

describe("分组框的名字里用拼音打中文", () => {
  //: 分组框和别的节点共用一个改名框(BoardNodeLabel),名字在 title 里;回车确认才落到画布上。
  it("组词期间不被改写,选词的回车不算确认,上屏后再回车名字是中文", async () => {
    const view = mount([frame]);
    await settle();
    act(() => {
      fireEvent.doubleClick(document.querySelector('[data-id="f1"] span[title]')!);
    });
    const box = document.querySelector<HTMLInputElement>('[data-id="f1"] input')!;
    expect(box).not.toBeNull();
    const writes = watchValueWrites(box);
    composeWithIme(box, ["j", "ji", "jia", "jiao", "jiaos", "jiaose"], "角色");
    expect(writes).toEqual([]);
    expect(box.value).toBe("角色");
    act(() => {
      fireEvent.keyDown(box, { key: "Enter" });
    });
    await settle();
    expect(view.emitted.at(-1)?.items.find((one) => one.id === "f1")?.title).toBe("角色");
  });
});
