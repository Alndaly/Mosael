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
  useI18n: () => (key: string) => (key === "transcriptSpeakerLabel" ? "说话人 {n}" : key),
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
    expect(screen.queryByTitle("说话人 1")).toBeNull();
  });

  it("分得出两个人时才挂,而且时间码、说话人、正文在同一横向栅格里", async () => {
    serveTranscript(["SPEAKER_00", "SPEAKER_01"]);
    const { container } = renderPanel();

    const sentenceText = await screen.findByText("第0句");
    await waitFor(() => expect(screen.getByTitle("说话人 1")).toBeInTheDocument());
    const speaker = screen.getByTitle("说话人 1");
    expect(screen.getByTitle("说话人 2")).toBeInTheDocument();
    // 栏里放得下的是人形图标 + 序号,完整名字在 title / aria-label 上。
    // 此前是一个光秃秃的 `00` 挨着时间码 `00:00.0` —— 用户问"这个绿色的 00 是什么"。
    expect(speaker.textContent).toBe("1");
    expect(speaker.querySelector("svg")).not.toBeNull();
    expect(speaker).toHaveAttribute("aria-label", "说话人 1");

    const row = container.querySelector(".group\\/sentence");
    expect(row?.className).toContain("grid-cols-[92px_minmax(0,1fr)]");
    // 时间码和说话人同在顶部元数据组里；正文是相邻的栅格列。
    expect(speaker.parentElement?.className).toContain("h-6");
    expect(speaker.parentElement?.className).toContain("items-center");
    expect(speaker.parentElement?.parentElement).toBe(row);
    expect(sentenceText.parentElement?.parentElement).toBe(row);
  });

  it("句子和时间码在同一套栅格里 —— 对齐是结构给的,不是手调的边距", async () => {
    serveTranscript(["SPEAKER_00"]);
    const { container } = renderPanel();

    await screen.findByText("第0句");
    const row = container.querySelector(".group\\/sentence");
    expect(row?.className).toContain("grid-cols-[58px_minmax(0,1fr)]");
    expect(row?.className).not.toContain("ml-[46px]");
  });

  it("正文过长时自然换行而不是截断", async () => {
    serveTranscript(["SPEAKER_00"]);
    const { container } = renderPanel();

    await screen.findByText("第0句");
    const body = container.querySelector(".group\\/sentence > p");
    expect(body?.className).toContain("whitespace-normal");
    expect(body?.className).toContain("leading-6");
    expect(body?.className).toContain("[overflow-wrap:anywhere]");
    expect(body?.className).not.toContain("truncate");
    expect(body?.className).not.toContain("whitespace-nowrap");
  });

  it("右侧行操作平时不占正文空间", async () => {
    serveTranscript(["SPEAKER_00"]);
    const { container } = renderPanel();

    await screen.findByText("第0句");
    const row = container.querySelector(".group\\/sentence");
    const actionRail = screen.getByLabelText("cutSentence").parentElement;
    expect(row?.className).not.toContain("pr-[22px]");
    expect(row?.className).not.toContain("pr-[40px]");
    expect(actionRail?.className).toContain("absolute");
    expect(actionRail?.className).toContain("opacity-0");
    expect(actionRail?.className).not.toContain("group-focus-within/sentence:opacity-100");
  });
});

describe("在此切一刀之后的行序", () => {
  // 用户撞到的:双语稿里中文和英文同在 0.4 秒开始,在「如果」后面切一刀,
  // 后半截「太年轻的爱注定要分开。」掉到了英文那行下面。切的是一句,两半就该挨着。
  it("被切开的一句,后半截紧跟在前半截后面", async () => {
    const transcript = {
      id: "tr1",
      language: "zh",
      segments: [
        {
          id: "zh",
          start_time: 0.4,
          end_time: 5,
          text: "如果太年轻的爱注定要分开。",
          speaker: null,
          tokens: [
            { start_time: 0.4, end_time: 1.1, text: "如果" },
            { start_time: 1.1, end_time: 5, text: "太年轻的爱注定要分开。" },
          ],
        },
        { id: "en", start_time: 0.4, end_time: 2.9, text: "Iflovethat", speaker: null, tokens: [] },
      ],
    };
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const body = String(input).includes("/transcript") ? transcript : [];
      return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    }) as never;
    const split = {
      id: "s1",
      workspace_id: "w1",
      revision: 2,
      tracks: [
        {
          id: "t1",
          kind: "video",
          clips: [
            { id: "left", asset_id: "a1", asset_kind: "video", timeline_start: 0, src_in: 0, src_out: 1.1 },
            { id: "right", asset_id: "a1", asset_kind: "video", timeline_start: 1.1, src_in: 1.1, src_out: 6 },
          ],
        },
      ],
    } as never;
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(
      <QueryClientProvider client={client}>
        <TranscriptPanel sequence={split} onCutSegment={vi.fn()} />
      </QueryClientProvider>,
    );

    await screen.findByText("如果");
    const rows = [...container.querySelectorAll(".group\\/sentence > p")].map((row) => row.textContent);
    expect(rows.slice(0, 2)).toEqual(["如果", "太年轻的爱注定要分开。"]);
    expect(rows.indexOf("Iflovethat")).toBeGreaterThan(1);
  });
});
