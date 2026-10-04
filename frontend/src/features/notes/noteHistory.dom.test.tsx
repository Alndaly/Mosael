/** @vitest-environment jsdom */
/**
 * 笔记的版本记录弹窗:大弹窗,左边按天分组的版本列表,右边按阅读宽度排的预览。
 *
 * - 时间跟界面语言:中文「今天 / 昨天 / 10月2日」+「13:03」,英文「Today」+「1:03 PM」;精确到秒的完整时间在悬停说明里;
 * - 列表顶上那一版标「当前版本」,当前版本上没有「恢复」;
 * - 「恢复此版本」先确认,说清会新建一个版本、现有版本都还在;
 * - 「复制这一版的内容」;键盘上下键切换版本;
 * - 只有一个版本时说一句合适的话,不摆恢复按钮;
 * - 右边能切「预览 / 和当前版本对比 / 和上一版对比」:对比按字(删去的划掉、新加的高亮),大段没改的折起来;
 * - 每一版写清怎么来的(手动编辑 / 智能体修改 / 从版本 N 恢复……),别人写的带上名字,自己写的不念自己;
 * - 连续的手动编辑在后端合成一项:写着这一组改了多少,「N 次连续编辑」点开看得到组里的每一版。
 */
import React from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";

const prefs = vi.hoisted(() => ({ locale: "zh-CN" }));
vi.mock("@/app/preferences", () => ({ usePreferences: () => prefs, useI18n: () => (key: string) => key }));
vi.mock("@/app/auth", () => ({ useAuth: () => ({ user: { id: "me" } }) }));

type Version = {
  revision: number; title: string; created_at: string; origin: string;
  created_by: string | null; created_by_name: string; restored_from: number | null;
  group_start: number; saves: number; started_at: string; chars_added: number; chars_removed: number; title_changed: boolean;
};
const api = vi.hoisted(() => ({
  versions: [] as Version[],
  groups: {} as Record<number, Version[]>,
  content: {} as Record<number, { title: string; markdown: string }>,
}));
vi.mock("@/api/domains/notes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/domains/notes")>()),
  listNoteRevisions: vi.fn(async (_ws: string, _id: string, group?: number) => (group ? api.groups[group] : api.versions)),
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
    version(3, new Date(2026, 9, 4, 13, 3, 38)),
    version(2, new Date(2026, 9, 3, 11, 24, 47)),
    version(1, new Date(2026, 9, 2, 12, 39, 50), { origin: "create" }),
  ];
  api.groups = {};
  api.content = {
    1: { title: "周报", markdown: "周一" },
    2: { title: "周报", markdown: "周一开会。" },
    3: { title: "周报", markdown: "周一开会。周二写脚本。" },
  };
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

/** 一版(或一组)的列表项:默认是自己手动编辑、单独一版、什么都没改。 */
function version(revision: number, at: Date, extra: Partial<Version> = {}): Version {
  return {
    revision, title: "周报", created_at: utc(at), origin: "edit", created_by: "me", created_by_name: "我自己", restored_from: null,
    group_start: revision, saves: 1, started_at: utc(at), chars_added: 0, chars_removed: 0, title_changed: false, ...extra,
  };
}

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
//: 按那一行右上角的版本号找 —— 「从版本 1 恢复」那一行的名字里也有「版本 1」。
const row = (revision: number) => {
  const found = within(list()).getAllByRole("button").find((one) => one.querySelector(".note-history-number")?.textContent === `版本 ${revision}`);
  if (!found) throw new Error(`没有版本 ${revision} 这一行`);
  return found;
};

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

const added = () => [...document.querySelectorAll(".note-history ins")].map((one) => one.textContent);
const removed = () => [...document.querySelectorAll(".note-history del")].map((one) => one.textContent);

it("和当前版本对比、和上一版对比:按字画出删去的和新加的", async () => {
  mount();
  await waitFor(() => expect(row(2)).toBeInTheDocument());
  fireEvent.click(row(2));
  await screen.findByText("周一开会。");
  const views = screen.getByRole("radiogroup", { name: "看这一版的方式" });
  expect(within(views).getByRole("radio", { name: "预览" })).toHaveAttribute("aria-checked", "true");

  fireEvent.click(within(views).getByRole("radio", { name: "和当前版本对比" }));
  await waitFor(() => expect(added()).toEqual(["周二写脚本。"]));
  expect(removed()).toEqual([]);
  expect(screen.getByText(/后来加上的/)).toBeInTheDocument();

  fireEvent.click(within(views).getByRole("radio", { name: "和上一版对比" }));
  await waitFor(() => expect(added()).toEqual(["开会。"]));
  expect(screen.getByText(/这一版加上的/)).toBeInTheDocument();

  //: 切到别的版本,看的方式不变。
  fireEvent.click(row(3));
  await waitFor(() => expect(added()).toEqual(["周二写脚本。"]));
});

it("当前版本没法和当前比,第 1 版没有上一版:那两项点不了", async () => {
  mount();
  await waitFor(() => expect(row(3)).toBeInTheDocument());
  const views = screen.getByRole("radiogroup", { name: "看这一版的方式" });
  expect(within(views).getByRole("radio", { name: "和当前版本对比" })).toBeDisabled();
  fireEvent.click(row(1));
  await screen.findByText("周一");
  expect(within(views).getByRole("radio", { name: "和上一版对比" })).toBeDisabled();
  expect(within(views).getByRole("radio", { name: "和当前版本对比" })).toBeEnabled();
});

it("改了标题也画出来;一模一样时说没有区别", async () => {
  api.content[2] = { title: "上周周报", markdown: "周一开会。周二写脚本。" };
  mount();
  await waitFor(() => expect(row(2)).toBeInTheDocument());
  fireEvent.click(row(2));
  await screen.findByText("上周周报");
  fireEvent.click(screen.getByRole("radio", { name: "和当前版本对比" }));
  await waitFor(() => expect(removed()).toEqual(["上周"]));
  expect(added()).toEqual([]);

  api.content[2] = { title: "周报", markdown: "周一开会。周二写脚本。" };
  cleanup();
  mount();
  await waitFor(() => expect(row(2)).toBeInTheDocument());
  fireEvent.click(row(2));
  await screen.findAllByText("周一开会。周二写脚本。");
  fireEvent.click(screen.getByRole("radio", { name: "和当前版本对比" }));
  expect(await screen.findByText("和当前版本没有区别。")).toBeInTheDocument();
});

it("大段没改的折起来,点一下展开", async () => {
  const lines = Array.from({ length: 30 }, (_, index) => `第 ${index + 1} 行`);
  api.content[2] = { title: "周报", markdown: lines.join("\n") };
  mount({ current: { revision: 3, title: "周报", markdown: [...lines.slice(0, 29), "第 30 行,改过"].join("\n") } });
  await waitFor(() => expect(row(2)).toBeInTheDocument());
  fireEvent.click(row(2));
  await screen.findByText(/第 1 行/);
  fireEvent.click(screen.getByRole("radio", { name: "和当前版本对比" }));
  const unfold = await screen.findByRole("button", { name: "展开未改动的 27 行" });
  expect(screen.queryByText("第 5 行")).toBeNull();
  expect(screen.getByText("第 28 行")).toBeInTheDocument();
  fireEvent.click(unfold);
  expect(screen.getByText("第 5 行")).toBeInTheDocument();
  expect(added()).toEqual([",改过"]);
});

it("每一版写清怎么来的:手动编辑、智能体修改、从版本 N 恢复;别人写的带上名字", async () => {
  api.versions[0] = { ...api.versions[0], origin: "restore", restored_from: 1 };
  api.versions[1] = { ...api.versions[1], origin: "agent", created_by: "u2", created_by_name: "小王" };
  mount();
  await waitFor(() => expect(row(3)).toBeInTheDocument());
  expect(row(3)).toHaveTextContent("从版本 1 恢复");
  expect(row(2)).toHaveTextContent("智能体修改");
  expect(row(2)).toHaveTextContent("小王");
  expect(row(1)).toHaveTextContent("新建");
  expect(row(1)).not.toHaveTextContent("我自己");

  fireEvent.click(row(2));
  await waitFor(() => expect(document.querySelector(".note-history-what")).toHaveTextContent("智能体修改 · 小王"));
});

function burst() {
  //: 第 2、3、4 版是一口气写的,合成一项(列表上是第 4 版);第 1 版是新建。
  api.versions = [
    version(4, new Date(2026, 9, 4, 13, 3, 38), { group_start: 2, saves: 3, started_at: utc(new Date(2026, 9, 4, 13, 2, 14)), chars_added: 11, chars_removed: 2 }),
    version(1, new Date(2026, 9, 4, 12, 39, 50), { origin: "create", chars_added: 2 }),
  ];
  api.groups = { 2: [
    api.versions[0],
    version(3, new Date(2026, 9, 4, 13, 2, 20), { group_start: 2 }),
    version(2, new Date(2026, 9, 4, 13, 2, 14), { group_start: 2 }),
  ] };
  api.content[3] = { title: "周报", markdown: "周一开会。周二" };
  api.content[4] = { title: "周报", markdown: "周一开会。周二写脚本。" };
  return { revision: 4, ...api.content[4] };
}

it("连续编辑合成一项:写着这一组改了多少,「3 次连续编辑」点开看得到组里的每一版", async () => {
  mount({ current: burst() });
  await waitFor(() => expect(row(4)).toBeInTheDocument());
  expect(row(4)).toHaveTextContent("+11");
  expect(row(4)).toHaveTextContent("−2");
  expect(row(4)).toHaveTextContent("字");
  expect(row(1)).toHaveTextContent("+2");
  expect(within(list()).queryByText("版本 3")).toBeNull();

  const fold = within(list()).getByRole("button", { name: "3 次连续编辑" });
  expect(fold).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(fold);
  await waitFor(() => expect(row(3)).toBeInTheDocument());
  expect(row(2)).toBeInTheDocument();
  expect(within(list()).getAllByText("版本 4")).toHaveLength(1);
  expect(row(3)).toHaveTextContent("13:02:20");

  //: 组里的一版和紧挨着它的前一版比;整组和这一组之前那一版比。
  fireEvent.click(row(3));
  await screen.findByText("周一开会。周二");
  fireEvent.click(screen.getByRole("radio", { name: "和上一版对比" }));
  await waitFor(() => expect(added()).toEqual(["周二"]));
  fireEvent.click(row(4));
  await waitFor(() => expect(added()).toEqual(["开会。周二写脚本。"]));

  row(4).focus();
  fireEvent.keyDown(row(4), { key: "ArrowDown" });
  expect(row(3)).toHaveAttribute("aria-current", "true");
});

it("引用的是组里的一版:进来时那一组已经展开、选中那一版", async () => {
  const current = burst();
  mount({ current, focusRevision: 3 });
  await waitFor(() => expect(row(3)).toHaveAttribute("aria-current", "true"));
  expect(within(list()).getByRole("button", { name: "3 次连续编辑" })).toHaveAttribute("aria-expanded", "true");
});

it("只改了标题、只改了属性,也写出来", async () => {
  api.versions[0] = { ...api.versions[0], title_changed: true };
  mount();
  await waitFor(() => expect(row(3)).toBeInTheDocument());
  expect(row(3)).toHaveTextContent("改了标题");
  expect(row(2)).toHaveTextContent("属性有改动");
  expect(row(1)).not.toHaveTextContent("属性有改动");
});

it("只有一项但它是好几次连续编辑:不算只有一个版本", async () => {
  const current = burst();
  api.versions = api.versions.slice(0, 1);
  mount({ current });
  await waitFor(() => expect(row(4)).toBeInTheDocument());
  expect(screen.queryByText(/目前只有这一个版本/)).toBeNull();
});
