/** @vitest-environment jsdom */
/**
 * 带着笔记选区发出去的消息:气泡里多一行可点的摘录(笔记标题 + 选区开头一截),和引用笔记的胶囊同一个样子;
 * 点了先问一句那篇还在不在,在就回到那篇笔记、把那段定位出来(lib/deepLink 的定位请求)。回看历史时也在 ——
 * 它存在消息的 payload.quote 里,不是发送那一刻的界面状态。
 */
import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { NOTE_PASSAGE_EVENT } from "@/lib/deepLink";

const apiCall = vi.fn();
vi.mock("@/api/transport", () => ({ api: (path: string) => apiCall(path) }));
vi.mock("@/api/client", () => ({ assetFileUrl: (id: string) => `/file/${id}`, assetPreviewUrl: (id: string) => `/p/${id}` }));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => ({ agentRefGone: "「{name}」已经不在了", agentRefGoneHint: "可能已被删除" })[key] ?? key,
}));
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview: vi.fn() }) }));
const toastError = vi.fn();
vi.mock("sonner", () => ({ toast: { error: (...args: unknown[]) => toastError(...args) } }));
vi.mock("@/features/media/AssetPreviewModalById", () => ({ useAssetPreviewModal: () => ({ openAsset: vi.fn(), modal: null }) }));

import { UserMessageContent } from "./userMessage";

const quote = { kind: "note" as const, note_id: "n1", title: "宣传片周报", text: "周二把**脚本第二稿**写完,重点改了产品演示那一段", start: 42 };
const located: string[] = [];
const onLocate = (event: Event) => located.push(String((event as CustomEvent).detail));

beforeEach(() => {
  apiCall.mockReset();
  toastError.mockReset();
  located.length = 0;
  window.location.hash = "";
  window.addEventListener(NOTE_PASSAGE_EVENT, onLocate);
});
afterEach(() => window.removeEventListener(NOTE_PASSAGE_EVENT, onLocate));

it("气泡里一行摘录:笔记标题 + 选区开头(去掉 Markdown 记号),和引用笔记同一种胶囊", () => {
  render(<UserMessageContent content="把这段改得口语一些" document={null} quote={quote} />);
  const chip = screen.getByRole("button", { name: /宣传片周报/ });
  expect(chip).toHaveAttribute("data-agent-ref-kind", "note");
  expect(chip.textContent).toContain("宣传片周报");
  expect(chip.textContent).toContain("周二把脚本第二稿写完");
  expect(chip.textContent).not.toContain("**");
});

it("点它:那篇还在就回到笔记,并把那段的原文和位置交给笔记页去定位", async () => {
  apiCall.mockResolvedValue({ id: "n1" });
  render(<UserMessageContent content="把这段改得口语一些" document={null} quote={quote} />);
  await userEvent.click(screen.getByRole("button", { name: /宣传片周报/ }));
  await vi.waitFor(() => expect(window.location.hash).toContain("note=n1"));
  expect(located.map((raw) => JSON.parse(raw))).toEqual([{ noteId: "n1", text: quote.text, start: 42 }]);
});

it("那篇已经删了:直说,不跳", async () => {
  apiCall.mockRejectedValue(new Error("404"));
  render(<UserMessageContent content="看看" document={null} quote={quote} />);
  await userEvent.click(screen.getByRole("button", { name: /宣传片周报/ }));
  await vi.waitFor(() => expect(toastError).toHaveBeenCalled());
  expect(window.location.hash).toBe("");
  expect(located).toEqual([]);
});

it("没带摘录的消息没有这一行", () => {
  render(<UserMessageContent content="普通的一句" document={null} />);
  expect(screen.queryByRole("button")).toBeNull();
});
