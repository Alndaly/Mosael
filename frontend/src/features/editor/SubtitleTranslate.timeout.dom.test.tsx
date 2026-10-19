/** @vitest-environment jsdom */
/**
 * 翻译超时/用完总预算时,用户看到的是**一句说清楚的失败**,不是永远「翻译中」。
 *
 * 真正的计时在上一条链的出口上钉着(api/translateGuards.test):一批有 2 分钟预算、整次有
 * 15 分钟总预算。这里只钉 UI 那一半:出口抛出 `TranslationTimeout` /
 * `TranslationDeadlineExceeded` 之后,弹层里说的是「翻译超时 + 多少秒/分钟」,并且转圈停了。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
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
    subtitleTranslateBilingual: "保留原文(双语)",
    subtitleTranslateApply: "翻译全部 {n} 条",
    subtitleTranslateApplySelected: "翻译选中 {n} 条",
    subtitleTranslateProgress: "翻译中 {done}/{total}…",
    subtitleTranslateNote: "就地替换字幕文本,可撤销",
    subtitleTranslateTimedOut: "翻译超时",
    subtitleTranslateTimeout: "翻译服务在 {seconds} 秒内没有响应,已停止。",
    subtitleTranslateDeadline: "这次翻译超过 {minutes} 分钟还没完成,已停止。",
    subtitleTranslatePartial: "前 {n} 条已写入轨道,其余保持原文。",
  } as Record<string, string>,
}));

const toastMock = vi.hoisted(() =>
  Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn(), message: vi.fn() }),
);
vi.mock("sonner", () => ({ toast: toastMock }));

const translateMock = vi.hoisted(() => vi.fn());
vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  return { ...actual, translateTexts: translateMock };
});

vi.stubGlobal("ResizeObserver", class {
  observe() {}
  unobserve() {}
  disconnect() {}
});

import { TranslationDeadlineExceeded, TranslationTimeout } from "@/api/client";
import { SubtitlePanel } from "@/features/editor/SubtitlePanel";

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

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SubtitlePanel
        sequence={sequenceWith(["a", "b", "c"])}
        onSetText={vi.fn()}
        onAddSubtitle={vi.fn()}
        onDeleteClip={vi.fn()}
        onApplyTexts={vi.fn(async () => undefined)}
      />
    </QueryClientProvider>,
  );
}

async function start(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: "翻译" }));
  await user.click(await screen.findByRole("button", { name: "翻译全部 3 条" }));
}

beforeEach(() => {
  translateMock.mockReset();
  toastMock.mockClear();
  toastMock.error.mockClear();
  toastMock.success.mockClear();
  toastMock.message.mockClear();
  vi.stubGlobal("fetch", vi.fn(async () => new Response("[]", {
    status: 200,
    headers: { "content-type": "application/json" },
  })));
});

describe("字幕翻译 · 超时说清楚", () => {
  it("一批超时:说「翻译超时」+ 120 秒,并停止转圈", async () => {
    translateMock.mockRejectedValue(new TranslationTimeout(120_000));
    const user = userEvent.setup();
    renderPanel();
    await start(user);

    await waitFor(() =>
      expect(toastMock.error).toHaveBeenCalledWith(
        "翻译超时",
        expect.objectContaining({ description: expect.stringContaining("120 秒") }),
      ),
    );
    expect(screen.queryByText(/翻译中/)).toBeNull();
  });

  it("整次用完总预算:说「超过 15 分钟还没完成」", async () => {
    translateMock.mockRejectedValue(new TranslationDeadlineExceeded(15 * 60_000));
    const user = userEvent.setup();
    renderPanel();
    await start(user);

    await waitFor(() =>
      expect(toastMock.error).toHaveBeenCalledWith(
        "翻译超时",
        expect.objectContaining({ description: expect.stringContaining("15 分钟") }),
      ),
    );
  });
});
