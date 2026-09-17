/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { describe, expect, it, vi } from "vitest";

/**
 * 字幕面板:列表本身,以及去「配音」页的入口。
 *
 * 配音不在这里做(表单在配音页,见 VoicePanel.dom.test)。这里钉住的是**入口还在**:
 * 每条字幕旁边一个 —— 「就这一条重配一下」时你正看着它、手就在它上面 —— 点了要选中那一条
 * 再切过去,配音页的范围跟着选中走。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { SubtitlePanel } from "@/features/editor/SubtitlePanel";
import { useEditorStore } from "@/stores/editorStore";

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
          timeline_start: index * 5,
          src_in: 0,
          src_out: 3,
          speed: 1,
          text_override: text,
        })),
      },
    ],
  } as never;
}

function renderPanel(texts: string[], onDub?: () => void) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SubtitlePanel
        sequence={sequenceWith(texts)}
        onSetText={vi.fn()}
        onAddSubtitle={vi.fn()}
        onDeleteClip={vi.fn()}
        onDub={onDub}
      />
    </QueryClientProvider>,
  );
}

describe("字幕列表空状态", () => {
  it("没有字幕时整块居中,而不是钉在顶上留一屏空白", () => {
    const { container } = renderPanel([]);
    const list = container.querySelector(".overflow-y-auto");
    // jsdom 没有真实布局,量不了像素;钉住的是**决定布局的那个类**,回归时它会先没。
    expect(list?.className).toContain("content-center");
    expect(list?.className).not.toContain("content-start");
  });

  it("有字幕时贴顶排列 —— 居中只属于空状态", () => {
    const { container } = renderPanel(["一条"]);
    const list = container.querySelector(".overflow-y-auto");
    expect(list?.className).toContain("content-start");
    expect(list?.className).not.toContain("content-center");
  });
});

describe("去配音页的入口", () => {
  it("每条字幕自己带一个入口", () => {
    renderPanel(["第一条", "第二条"], vi.fn());
    expect(screen.getAllByLabelText("subtitleDubThis")).toHaveLength(2);
  });

  it("点某一条的入口:选中那一条,再切到配音页", async () => {
    const onDub = vi.fn();
    renderPanel(["第一条", "第二条"], onDub);
    await userEvent.click(screen.getAllByLabelText("subtitleDubThis")[1]);
    expect(useEditorStore.getState().selectedClipIds).toEqual(["c1"]);
    expect(onDub).toHaveBeenCalledOnce();
  });

  it("底部的「配音」也切过去,不再在这里弹一张表单", async () => {
    const onDub = vi.fn();
    renderPanel(["一条"], onDub);
    await userEvent.click(screen.getByRole("button", { name: "subtitleDub" }));
    expect(onDub).toHaveBeenCalledOnce();
    expect(screen.queryByText("subtitleDubLine")).toBeNull();
  });
});
