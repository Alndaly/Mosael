/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 确认卡是智能体写操作与执行之间唯一的闸,所以「哪一个在转」必须指向**你刚点的那一个**。
 *
 * 三个按钮共用一个 mutation 的 isPending,于是点「允许一次」时三个一起转 —— 而且同屏有第二张
 * 卡时,那张卡的三个也一起转。转圈是"我正在做这件事"的意思;六个一起转说的是另一件事,而在
 * 一张需要知情同意的卡上,这个歧义正好落在最不该有歧义的地方。
 */

const TEMPLATES: Record<string, string> = {
  confirmAllowOnce: "允许一次",
  confirmAllowSession: "本会话始终允许",
  confirmReject: "拒绝",
};

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => TEMPLATES[key] ?? key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

vi.mock("@/components/agent/confirmSurface", () => ({ registerInlineConfirmSurface: () => () => {} }));

const pendingCards = [
  { id: "c1", tool: "edit_timeline", summary: "改时间线", permission: "write", payload: {} },
  { id: "c2", tool: "render_sequence", summary: "导出", permission: "write", payload: {} },
];

/** 决策请求停在这里,好在"正在飞"的那一刻断言。 */
let releaseDecision: () => void = () => {};

const api = vi.fn(async (path: string, _init?: unknown) => {
  if (path.startsWith("/api/confirmations?")) return pendingCards;
  if (path.startsWith("/api/agent/sessions/")) return { id: "s1", auto_allow_tools: [] };
  await new Promise<void>((resolve) => {
    releaseDecision = resolve;
  });
  return { id: "c1", status: "approved" };
});

vi.mock("@/api/client", () => ({ api: (path: string, init?: unknown) => api(path, init) }));

import { InlineConfirmations } from "@/components/agent/InlineConfirmations";

function renderCards() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <InlineConfirmations workspaceId="w1" allowKey="s1" />
    </QueryClientProvider>,
  );
}

/** 转圈的按钮 —— Button 在 loading 时置 aria-busy。 */
function busyLabels(container: HTMLElement): string[] {
  return [...container.querySelectorAll("button[aria-busy]")].map((node) => node.textContent?.trim() ?? "");
}

describe("确认卡的等待状态", () => {
  beforeEach(() => {
    api.mockClear();
  });

  it("只有被点的那个按钮转圈", async () => {
    const { container } = renderCards();
    const buttons = await screen.findAllByText("允许一次");

    buttons[0].click();

    await waitFor(() => expect(busyLabels(container).length).toBeGreaterThan(0));
    expect(busyLabels(container)).toEqual(["允许一次"]);
    releaseDecision();
  });

  it("同一张卡的另外两个禁掉,但不转圈 —— 一张卡只能有一个结论", async () => {
    const { container } = renderCards();
    (await screen.findAllByText("允许一次"))[0].click();

    await waitFor(() => expect(busyLabels(container).length).toBe(1));
    const card = container.querySelectorAll("[role='region'] > div")[0];
    const disabled = [...card.querySelectorAll("button")].filter((node) => node.hasAttribute("disabled"));
    expect(disabled.length).toBe(3);
    releaseDecision();
  });

  it("另一张卡完全不受影响 —— 它等的不是同一件事", async () => {
    const { container } = renderCards();
    (await screen.findAllByText("允许一次"))[0].click();

    await waitFor(() => expect(busyLabels(container).length).toBe(1));
    const second = container.querySelectorAll("[role='region'] > div")[1];
    expect([...second.querySelectorAll("button")].some((node) => node.hasAttribute("disabled"))).toBe(false);
    releaseDecision();
  });

  it("「本会话始终允许」要写白名单再批准,整段都转它自己那一个", async () => {
    const { container } = renderCards();
    (await screen.findAllByText("本会话始终允许"))[0].click();

    // 第一步(写白名单)与第二步(批准)之间不能换一个按钮转 —— 用户看到的是同一个动作。
    await waitFor(() => expect(busyLabels(container).length).toBe(1));
    expect(busyLabels(container)).toEqual(["本会话始终允许"]);
    releaseDecision();
  });
});
