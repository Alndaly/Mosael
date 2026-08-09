/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * 逐字稿列表读起来要像一段**文稿**,而不是一列带前缀的行。
 *
 * 用户给的截图里,两句话前面各挂着一个一模一样的 `[说话人 00]` —— 单人口播是最常见的输入,
 * 而那个标签在每一行重复同一件事:把正文往右顶,还抢走第一眼。分得出两个人时它才是信息。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { TranscriptPanel } from "@/features/editor/TranscriptPanel";

// jsdom 没有实现它,而面板会把当前句滚进视野。
Element.prototype.scrollIntoView = vi.fn();

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

function sequenceWith(clipId: string) {
  return {
    id: "s1",
    workspace_id: "w1",
    revision: 1,
    tracks: [
      {
        id: "t1",
        kind: "video",
        clips: [
          {
            id: clipId,
            asset_id: "a1",
            asset_kind: "video",
            timeline_start: 0,
            src_in: 0,
            src_out: 60,
          },
        ],
      },
    ],
  } as never;
}

function serveTranscript(speakers: Array<string | null>) {
  const transcript = {
    id: "tr1",
    language: "zh",
    segments: speakers.map((speaker, index) => ({
      id: `seg${index}`,
      start_time: index * 10,
      end_time: index * 10 + 5,
      text: `第${index}句`,
      speaker,
      tokens: [{ start_time: index * 10, end_time: index * 10 + 5, text: `第${index}句` }],
    })),
  };
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const body = url.includes("/transcript") ? transcript : [];
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }) as never;
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TranscriptPanel sequence={sequenceWith("c1")} onCutSegment={vi.fn()} />
    </QueryClientProvider>,
  );
}

describe("逐字稿列表", () => {
  it("只有一个说话人时不挂说话人标签 —— 每行都一样的东西不是信息", async () => {
    serveTranscript(["SPEAKER_00", "SPEAKER_00"]);
    renderPanel();

    await screen.findByText("第0句");
    expect(screen.queryByTitle("说话人 00")).toBeNull();
  });

  it("分得出两个人时才挂,而且挂在时间码那一栏里", async () => {
    serveTranscript(["SPEAKER_00", "SPEAKER_01"]);
    renderPanel();

    await screen.findByText("第0句");
    await waitFor(() => expect(screen.getByTitle("说话人 00")).toBeInTheDocument());
    expect(screen.getByTitle("说话人 01")).toBeInTheDocument();
    // 栏里放得下的是编号本身,完整名字在 title 上。
    expect(screen.getByTitle("说话人 00").textContent).toBe("00");
  });

  it("句子和时间码在同一套栅格里 —— 对齐是结构给的,不是手调的边距", async () => {
    serveTranscript(["SPEAKER_00"]);
    const { container } = renderPanel();

    await screen.findByText("第0句");
    const row = container.querySelector(".group\\/sentence");
    expect(row?.className).toContain("grid-cols-[50px_minmax(0,1fr)]");
    expect(row?.className).not.toContain("ml-[46px]");
  });
});
