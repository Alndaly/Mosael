/** @vitest-environment jsdom */
/**
 * 剪辑页「字幕 → 翻译」这条链的三个用户可见事实:
 *
 * 1. 进度**按批**往前走,不是攒完才从 0 跳到底;
 * 2. 翻译中能**取消**,停得下来,并说清轨道上有没有留下半份;
 * 3. 连接失败/超时说「连不上 / 超时」,不是永远「翻译中」。
 *
 * 真机反馈是「翻译中 0/1039…」一直不动、也无法取消。这里用真的 `translateTexts` + 打桩的
 * `fetch`,从按钮一路测到 toast,而不是只测纯函数。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => strings.templates[key] ?? key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

const strings = vi.hoisted(() => ({
  templates: {
    cancel: "取消",
    subtitleTranslate: "翻译",
    subtitleTranslateTo: "目标语言",
    subtitleTranslateEngine: "翻译引擎",
    subtitleTranslateEngineDefault: "按默认",
    subtitleTranslateSelectedOnly: "仅选中的 {n} 条",
    subtitleTranslateBilingual: "保留原文(双语)",
    subtitleTranslateApply: "翻译全部 {n} 条",
    subtitleTranslateApplySelected: "翻译选中 {n} 条",
    subtitleTranslateProgress: "翻译中 {done}/{total}…",
    subtitleTranslateNote: "就地替换字幕文本,可撤销",
    subtitleTranslateDone: "已翻译 {n} 条字幕",
    subtitleTranslateFailed: "翻译失败",
    subtitleTranslatePartial: "前 {n} 条已写入轨道,其余保持原文。",
    subtitleTranslateCancelled: "已取消翻译",
    subtitleTranslateCancelledNone: "没有写入任何字幕。",
    subtitleTranslateTimedOut: "翻译超时",
    subtitleTranslateTimeout: "翻译服务在 {seconds} 秒内没有响应,已停止。",
    subtitleTranslateDeadline: "这次翻译超过 {minutes} 分钟还没完成,已停止。",
    subtitleTranslateUnreachable: "连不上翻译服务",
  } as Record<string, string>,
}));

const toastMock = vi.hoisted(() =>
  Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn(), message: vi.fn() }),
);
vi.mock("sonner", () => ({ toast: toastMock }));

vi.stubGlobal("ResizeObserver", class {
  observe() {}
  unobserve() {}
  disconnect() {}
});

import { SubtitlePanel } from "@/features/editor/SubtitlePanel";
import { useEditorStore } from "@/features/editor/editorStore";

const fetchMock = vi.fn();
type Pending = { init: RequestInit; resolve: (response: Response) => void };
let pending: Pending[] = [];

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

function sequenceWith(texts: string[]) {
  return {
    id: "s1",
    workspace_id: "w1",
    revision: 1,
    tracks: [
      {
        id: "t1",
        kind: "subtitle",
        clips: texts.map((text, index) => ({
          id: `c${index}`,
          asset_id: null,
          asset_kind: "",
          timeline_start: index * 2,
          src_in: 0,
          src_out: 1,
          speed: 1,
          text_override: text,
        })),
      },
    ],
  } as never;
}

function renderPanel(texts: string[], onApplyTexts = vi.fn(async () => undefined)) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SubtitlePanel
        sequence={sequenceWith(texts)}
        onSetText={vi.fn()}
        onAddSubtitle={vi.fn()}
        onDeleteClip={vi.fn()}
        onApplyTexts={onApplyTexts}
      />
    </QueryClientProvider>,
  );
  return { onApplyTexts };
}

/** 把当前挂起的那一批按「每条前面加 T:」回掉。 */
async function resolveBatch(index: number) {
  const call = pending[index];
  const body = JSON.parse(String(call.init.body)) as { texts: string[] };
  await act(async () => {
    call.resolve(jsonResponse({ translations: body.texts.map((text) => `T:${text}`) }));
  });
}

beforeEach(() => {
  pending = [];
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  useEditorStore.setState({ selectedClipIds: [] });
  toastMock.mockClear();
  toastMock.error.mockClear();
  toastMock.success.mockClear();
  toastMock.message.mockClear();
  fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input).includes("/api/settings/capabilities")) return Promise.resolve(jsonResponse([]));
    return new Promise<Response>((resolve, reject) => {
      const signal = init?.signal;
      signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
      pending.push({ init: init ?? {}, resolve });
    });
  });
});

describe("字幕翻译 · 进度", () => {
  it("每批完成就动一步:0/375 → 125/375 → 250/375 → 完成", async () => {
    const user = userEvent.setup();
    const { onApplyTexts } = renderPanel(Array.from({ length: 375 }, (_, i) => `cue-${i}`));
    await user.click(await screen.findByRole("button", { name: "翻译" }));
    await user.click(await screen.findByRole("button", { name: "翻译全部 375 条" }));

    expect(await screen.findByText("翻译中 0/375…")).toBeInTheDocument();
    await waitFor(() => expect(pending.length).toBe(1));

    await resolveBatch(0);
    expect(await screen.findByText("翻译中 125/375…")).toBeInTheDocument();

    await resolveBatch(1);
    expect(await screen.findByText("翻译中 250/375…")).toBeInTheDocument();

    await resolveBatch(2);
    await waitFor(() => expect(toastMock.success).toHaveBeenCalledWith("已翻译 375 条字幕"));
    //: 一批一步落进轨道(既有的「边翻边落地」),三批三次;不是攒到最后一次写。
    expect(onApplyTexts).toHaveBeenCalledTimes(3);
  });
});

describe("字幕翻译 · 取消", () => {
  it("翻译中能点「取消」:停掉、说已取消、不留下半份", async () => {
    const user = userEvent.setup();
    const { onApplyTexts } = renderPanel(Array.from({ length: 375 }, (_, i) => `cue-${i}`));
    await user.click(await screen.findByRole("button", { name: "翻译" }));
    await user.click(await screen.findByRole("button", { name: "翻译全部 375 条" }));
    await waitFor(() => expect(pending.length).toBe(1));

    await user.click(await screen.findByRole("button", { name: "取消" }));

    await waitFor(() =>
      expect(toastMock.message).toHaveBeenCalledWith("已取消翻译", {
        description: "没有写入任何字幕。",
      }),
    );
    //: 在途的那一批真的被掐了(fetch 的 signal),而不是只在界面上装作停了。
    expect(pending[0].init.signal?.aborted).toBe(true);
    expect(onApplyTexts).not.toHaveBeenCalled();
    //: 没有「下一批」—— 取消之后不再发请求。
    expect(pending).toHaveLength(1);
  });
});

describe("字幕翻译 · 版面", () => {
  it("「翻译全部」铺满弹层这一列 —— 和上面两个下拉同宽", async () => {
    const user = userEvent.setup();
    renderPanel(["a", "b", "c"]);
    await user.click(await screen.findByRole("button", { name: "翻译" }));

    const apply = await screen.findByRole("button", { name: "翻译全部 3 条" });
    //: 弹层内容是一条 `flex-col` 的列,上面两个 Select 靠列的 stretch 铺满。这一颗动作也得是
    //: 列里的**直接一项** —— 此前它套在一行 `flex items-center` 里:行被拉满了,按钮还按内容宽,
    //: 于是它比上面那两个下拉短一截(维护者截图)。
    expect(apply.parentElement).toHaveClass("flex", "flex-col", "items-stretch");
    //: 宽度走容器、不写控件身上(见 design/controlOverrides.test.ts 的注:宽度是排版)。
    expect(apply).not.toHaveClass("w-full");
  });

  it("翻译中多出「取消」:并列两颗各自按内容宽,不铺满", async () => {
    const user = userEvent.setup();
    renderPanel(Array.from({ length: 375 }, (_, i) => `cue-${i}`));
    await user.click(await screen.findByRole("button", { name: "翻译" }));
    await user.click(await screen.findByRole("button", { name: "翻译全部 375 条" }));

    const cancel = await screen.findByRole("button", { name: "取消" });
    const row = cancel.parentElement;
    //: 一排并列的小按钮(「取消」+ 翻译中的主动作)各自按内容宽:铺满会把弹层读成两个主按钮。
    expect(row).toHaveClass("flex", "items-center");
    expect(row).not.toHaveClass("flex-col");
    expect(cancel).not.toHaveClass("w-full");
    expect(screen.getByRole("button", { name: /翻译中/ })).not.toHaveClass("w-full");
  });
});

describe("字幕翻译 · 连不上", () => {
  it("请求当场失败:说「连不上翻译服务」,不是继续「翻译中」", async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      if (String(input).includes("/api/settings/capabilities")) return Promise.resolve(jsonResponse([]));
      return Promise.reject(new TypeError("Failed to fetch"));
    });
    const user = userEvent.setup();
    renderPanel(["a", "b", "c"]);
    await user.click(await screen.findByRole("button", { name: "翻译" }));
    await user.click(await screen.findByRole("button", { name: "翻译全部 3 条" }));

    await waitFor(() =>
      expect(toastMock.error).toHaveBeenCalledWith("连不上翻译服务", expect.anything()),
    );
    expect(screen.queryByText(/翻译中/)).toBeNull();
  });
});
