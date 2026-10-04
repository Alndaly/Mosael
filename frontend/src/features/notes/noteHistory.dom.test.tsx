/** @vitest-environment jsdom */
/**
 * 笔记的版本记录弹窗:大弹窗,左边按天分组的版本列表,右边按阅读宽度排的预览。
 *
 * - 时间跟界面语言:中文「今天 / 昨天 / 10月2日」+「13:03」,英文「Today」+「1:03 PM」;精确到秒的完整时间在悬停说明里;
 * - 列表顶上那一版标「当前版本」,当前版本上没有「恢复」;
 * - 「恢复此版本」先确认,说清会新建一个版本、现有版本都还在;
 * - 「复制这一版的内容」;键盘上下键切换版本;
 * - 只有一个版本时说一句合适的话,不摆恢复按钮。
 */
import React from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";

const prefs = vi.hoisted(() => ({ locale: "zh-CN" }));
vi.mock("@/app/preferences", () => ({ usePreferences: () => prefs, useI18n: () => (key: string) => key }));

const api = vi.hoisted(() => ({
  versions: [] as { revision: number; title: string; created_at: string }[],
  content: {} as Record<number, { title: string; markdown: string }>,
}));
vi.mock("@/api/domains/notes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/domains/notes")>()),
  listNoteRevisions: vi.fn(async () => api.versions),
  getNoteRevision: vi.fn(async (_ws: string, _id: string, revision: number) => ({
    ...api.content[revision], revision, project_id: null, tags: [], topics: [], sources: [], favorite: false, trashed: false,
  })),
}));

const { NoteHistoryDialog } = await import("./NoteHistoryDialog");
const { versionMoment, versionFullTime } = await import("./versionTime");

//: 「现在」是 2026-10-04 下午三点(本地时间)。后端给的是不带时区标记的 UTC 串。
const NOW = new Date(2026, 9, 4, 15, 0, 0);
const utc = (local: Date) => local.toISOString().replace("Z", "");

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  prefs.locale = "zh-CN";
  api.versions = [
    { revision: 3, title: "周报", created_at: utc(new Date(2026, 9, 4, 13, 3, 38)) },
    { revision: 2, title: "周报", created_at: utc(new Date(2026, 9, 3, 11, 24, 47)) },
    { revision: 1, title: "周报", created_at: utc(new Date(2026, 9, 2, 12, 39, 50)) },
  ];
  api.content = {
    1: { title: "周报", markdown: "周一" },
    2: { title: "周报", markdown: "周一开会。" },
    3: { title: "周报", markdown: "周一开会。周二写脚本。" },
  };
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

function mount(props: Partial<React.ComponentProps<typeof NoteHistoryDialog>> = {}) {
  const onRestore = vi.fn(async () => {});
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <TooltipProvider>
        <NoteHistoryDialog open onOpenChange={() => {}} workspaceId="ws" noteId="n1"
          current={{ revision: 3, title: "周报", markdown: "周一开会。周二写脚本。" }} focusRevision={null} onRestore={onRestore} {...props} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return { onRestore };
}
const list = () => screen.getByRole("list", { name: "版本列表" });
const row = (revision: number) => within(list()).getByRole("button", { name: new RegExp(`版本 ${revision}(\\D|$)`) });

it("时间跟界面语言走,列表按天分组:今天 / 昨天 / 具体日期", async () => {
  mount();
  await waitFor(() => expect(row(3)).toBeInTheDocument());
  const headings = within(list()).getAllByRole("heading").map((one) => one.textContent);
  expect(headings[0]).toBe("今天");
  expect(headings[1]).toBe("昨天");
  expect(headings[2]).toMatch(/10月2日/);
  expect(row(3)).toHaveTextContent("13:03");
  expect(row(3)).not.toHaveTextContent(/PM|AM|\//);

  expect(versionMoment(utc(new Date(2026, 9, 4, 13, 3, 38)), "zh-CN", NOW, { today: "今天", yesterday: "昨天" })).toBe("今天 13:03");
  expect(versionMoment(utc(new Date(2026, 9, 3, 12, 39, 0)), "zh-CN", NOW, { today: "今天", yesterday: "昨天" })).toBe("昨天 12:39");
  expect(versionMoment(utc(new Date(2026, 8, 3, 12, 39, 0)), "zh-CN", NOW, { today: "今天", yesterday: "昨天" })).toBe("9月3日 12:39");
  expect(versionMoment(utc(new Date(2025, 8, 3, 12, 39, 0)), "zh-CN", NOW, { today: "今天", yesterday: "昨天" })).toBe("2025年9月3日 12:39");
  expect(versionMoment(utc(new Date(2026, 9, 4, 13, 3, 38)), "en-US", NOW, { today: "Today", yesterday: "Yesterday" })).toBe("Today, 1:03 PM");
  expect(versionFullTime(utc(new Date(2026, 9, 4, 13, 3, 38)), "zh-CN")).toMatch(/2026年10月4日.*13:03:38/);
  expect(versionFullTime(utc(new Date(2026, 9, 4, 13, 3, 38)), "en-US")).toMatch(/October 4, 2026.*1:03:38\sPM/);
});

it("英文界面用英文的说法", async () => {
  prefs.locale = "en-US";
  mount();
  const versions = await screen.findByRole("list", { name: "Versions" });
  await waitFor(() => expect(within(versions).getAllByRole("heading")[0]).toHaveTextContent("Today"));
  expect(within(versions).getByRole("button", { name: /Version 3/ })).toHaveTextContent("1:03 PM");
});

it("顶上那一版是当前版本:标出来,而且没有「恢复」;选旧的一版才有", async () => {
  mount();
  await waitFor(() => expect(row(3)).toBeInTheDocument());
  expect(row(3)).toHaveTextContent("当前版本");
  expect(row(3)).toHaveAttribute("aria-current", "true");
  expect(screen.queryByRole("button", { name: "恢复此版本" })).toBeNull();

  fireEvent.click(row(2));
  expect(row(2)).toHaveAttribute("aria-current", "true");
  expect(await screen.findByRole("button", { name: "恢复此版本" })).toBeInTheDocument();
  expect(await screen.findByText("周一开会。")).toBeInTheDocument();
});

it("恢复先确认:说清会新建一个版本、现有版本都还在;确认了才恢复", async () => {
  const { onRestore } = mount();
  await waitFor(() => expect(row(2)).toBeInTheDocument());
  fireEvent.click(row(2));
  await screen.findByText("周一开会。");
  fireEvent.click(screen.getByRole("button", { name: "恢复此版本" }));

  const confirm = await screen.findByRole("alertdialog");
  expect(confirm).toHaveTextContent("版本 2");
  expect(confirm).toHaveTextContent("新建版本 4");
  expect(confirm).toHaveTextContent("现有的版本都还在");
  fireEvent.click(within(confirm).getByRole("button", { name: "cancel" }));
  expect(onRestore).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("button", { name: "恢复此版本" }));
  fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "恢复" }));
  await waitFor(() => expect(onRestore).toHaveBeenCalledWith(2));
});

it("复制这一版的内容", async () => {
  const writeText = vi.fn(async () => {});
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  mount();
  await waitFor(() => expect(row(2)).toBeInTheDocument());
  fireEvent.click(row(2));
  await screen.findByText("周一开会。");
  fireEvent.click(screen.getByRole("button", { name: "复制这一版的内容" }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith("周一开会。"));
});

it("键盘上下键在版本之间切换,焦点跟着走", async () => {
  mount();
  await waitFor(() => expect(row(3)).toBeInTheDocument());
  row(3).focus();
  fireEvent.keyDown(row(3), { key: "ArrowDown" });
  expect(row(2)).toHaveAttribute("aria-current", "true");
  expect(document.activeElement).toBe(row(2));
  fireEvent.keyDown(row(2), { key: "End" });
  expect(row(1)).toHaveAttribute("aria-current", "true");
  fireEvent.keyDown(row(1), { key: "ArrowUp" });
  expect(row(2)).toHaveAttribute("aria-current", "true");
  expect(await screen.findByText("周一开会。")).toBeInTheDocument();
});

it("从「查看引用版本」进来,直接选中那一版", async () => {
  mount({ focusRevision: 1 });
  await waitFor(() => expect(row(1)).toHaveAttribute("aria-current", "true"));
  expect(await screen.findByText("周一")).toBeInTheDocument();
});

it("只有一个版本时说一句话,不摆恢复", async () => {
  api.versions = api.versions.slice(2);
  mount({ current: { revision: 1, title: "周报", markdown: "周一" } });
  expect(await screen.findByText(/目前只有这一个版本/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "恢复此版本" })).toBeNull();
});
