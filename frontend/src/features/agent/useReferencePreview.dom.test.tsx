/** @vitest-environment jsdom */
import React from "react";
import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";

const apiCall = vi.fn();
vi.mock("@/api/transport", () => ({ api: (path: string) => apiCall(path) }));
vi.mock("@/api/client", () => ({ assetFileUrl: (id: string) => `/file/${id}` }));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => ({ agentRefGone: "「{name}」已经不在了", agentRefGoneHint: "可能已被删除" })[key] ?? key,
}));
const openImagePreview = vi.fn();
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview }) }));
const toastError = vi.fn();
vi.mock("sonner", () => ({ toast: { error: (...args: unknown[]) => toastError(...args) } }));

import { useReferencePreview } from "./useReferencePreview";
import type { AgentReference } from "./references";

function Probe({ reference }: { reference: AgentReference }) {
  const open = useReferencePreview();
  return <button type="button" onClick={() => void open(reference)}>go</button>;
}
const click = async (reference: AgentReference) => {
  const view = render(<Probe reference={reference} />);
  await userEvent.click(view.getByRole("button"));
  return view;
};

beforeEach(() => {
  apiCall.mockReset();
  openImagePreview.mockReset();
  toastError.mockReset();
  window.location.hash = "";
});

/**
 * 「它还在不在」**只在点下去的那一刻才需要知道**。
 *
 * 想让删掉的胶囊看起来就不一样,就得在渲染时逐个查 —— 一屏几十条消息、每条几个引用,那是
 * 几百次请求,而绝大多数答案没人用到。发送时记一份"当时还在"更没用:常见情形恰恰是发出去
 * 之后才被删。所以现问。
 */
describe("点开引用", () => {
  it("对象没了就直说 —— 不是静默,也不是跳进一个空页面", async () => {
    apiCall.mockRejectedValue(new Error("404"));
    await click({ kind: "board", id: "b1", name: "故事板" });
    expect(toastError).toHaveBeenCalledWith("「故事板」已经不在了", { description: "可能已被删除" });
    // **没跳走**:此前是不问直接改 hash,于是落在一个空页面上。
    expect(window.location.hash).toBe("");
  });

  it("还在就跳过去", async () => {
    apiCall.mockResolvedValue({ id: "n1" });
    await click({ kind: "note", id: "n1", name: "笔记" });
    expect(window.location.hash).toContain("note=n1");
    expect(toastError).not.toHaveBeenCalled();
  });

  it("画板和工作流还要派一个打开事件 —— 只改 hash 的话,人已经在那一页上时点了没反应", async () => {
    // location.hash 不是响应式的:BoardsView / WorkflowsView 挂载时读一次 hash,之后只听
    // mosael:open-* 事件。所以正开着画板 A 时点画板 B 的引用,光改 hash 什么也不会发生。
    // 仓库里本来就有这条通道(gotoRecord 的三连发),此前绕过它直接写 hash 才把自己关在
    // "只有跨页才灵"的一半里。
    vi.useFakeTimers();
    try {
      const opened: string[] = [];
      const onBoard = (e: Event) => opened.push(String((e as CustomEvent).detail));
      window.addEventListener("mosael:open-board", onBoard);
      apiCall.mockResolvedValue({ id: "b9" });

      const view = render(<Probe reference={{ kind: "board", id: "b9", name: "分镜板" }} />);
      view.getByRole("button").click();
      await vi.waitFor(() => expect(window.location.hash).toContain("board=b9"));
      await vi.advanceTimersByTimeAsync(1000);   // 三连发 80/300/800ms

      expect(opened).toContain("b9");
      window.removeEventListener("mosael:open-board", onBoard);
    } finally {
      vi.useRealTimers();
    }
  });

  it("图片走灯箱", async () => {
    apiCall.mockResolvedValue({ id: "a1", name: "图", kind: "image" });
    await click({ kind: "asset", id: "a1", name: "图" });
    expect(openImagePreview).toHaveBeenCalledWith(expect.objectContaining({ src: "/file/a1", video: false }));
  });

  it("没有画面的素材去素材库里定位 —— 总比点了没反应强", async () => {
    // 此前音频/文档是 `if (kind !== image && !== video) return;`:点了什么都不发生。
    apiCall.mockResolvedValue({ id: "a2", name: "旁白", kind: "audio" });
    await click({ kind: "asset", id: "a2", name: "旁白" });
    expect(openImagePreview).not.toHaveBeenCalled();
    expect(window.location.hash).toContain("asset=a2");
  });

  it("只在点的时候问一次 —— 渲染时一次都不问", async () => {
    apiCall.mockResolvedValue({ id: "w1" });
    const view = render(<Probe reference={{ kind: "workflow", id: "w1", name: "流程" }} />);
    expect(apiCall).not.toHaveBeenCalled();
    await userEvent.click(view.getByRole("button"));
    expect(apiCall).toHaveBeenCalledTimes(1);
  });
});
