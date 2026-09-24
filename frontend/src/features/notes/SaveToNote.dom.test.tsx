/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 「保存到笔记」对话框的版面:先定写什么(形状 + 一句摘要),再定写到哪(新建 / 追加)。
 *
 * 钉住的是**结构**:形状是一个带名字的分段单选、两个去处各自是一个有标题的区块、已有笔记
 * 是一个有边界能自己滚的列表,行上有图标和更新时间、能用方向键走 —— 以及去处按下去调的
 * 仍然是原来那两个接口,参数不变。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/api/domains/notes", () => ({
  listNotes: vi.fn(),
  createNote: vi.fn(),
  appendNote: vi.fn(),
}));

import { appendNote, createNote, listNotes } from "@/api/domains/notes";
import { SaveToNote } from "./SaveToNote";

const note = (id: string, title: string, extra: Record<string, unknown> = {}) => ({
  id, title, workspace_id: "w1", revision: 3, markdown: "", project_id: null, tags: [], topics: [], sources: [],
  favorite: false, trashed: false, created_at: "2026-01-01T00:00:00", updated_at: new Date(Date.now() - 2 * 3600_000).toISOString(),
  ...extra,
});
const variants = [
  { id: "plain", label: "正文", markdown: "一二三", sources: [] },
  { id: "cited", label: "带时间戳引用", markdown: "> 一二三四五", sources: [{ kind: "asset" as const, id: "a1", label: "a", quote: "" }] },
];

function open(props: Partial<React.ComponentProps<typeof SaveToNote>> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SaveToNote workspaceId="w1" variants={variants} label="全部存为笔记" {...props} />
    </QueryClientProvider>,
  );
  return userEvent.click(screen.getByRole("button", { name: "全部存为笔记" }));
}

beforeEach(() => {
  vi.mocked(listNotes).mockReset().mockResolvedValue([note("n1", "第一篇"), note("n2", "第二篇"), note("gone", "回收站里的", { trashed: true })] as never);
  vi.mocked(createNote).mockReset().mockResolvedValue(note("new", "新") as never);
  vi.mocked(appendNote).mockReset().mockResolvedValue(note("n1", "第一篇") as never);
});

describe("正文形状", () => {
  it("是一个带名字的分段单选,切换后摘要跟着变", async () => {
    await open();
    const group = screen.getByRole("radiogroup", { name: "正文形状" });
    expect(group.className).toContain("rounded-lg"); // 走 SEGMENTED_LIST,不是一排裸按钮
    const radios = within(group).getAllByRole("radio");
    expect(radios).toHaveLength(2);
    expect(radios[0]).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText("将写入约 3 字，附 0 条来源")).toBeInTheDocument();
    await userEvent.click(radios[1]);
    expect(radios[1]).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText("将写入约 7 字，附 1 条来源")).toBeInTheDocument();
  });

  it("只有一种正文时不摆切换", async () => {
    await open({ variants: undefined, content: "一段话" });
    expect(screen.queryByRole("radiogroup")).toBeNull();
  });
});

describe("两个去处", () => {
  it("新建与追加是两个各自有标题的区块", async () => {
    await open();
    const create = screen.getByRole("region", { name: "存为新笔记" });
    const append = screen.getByRole("region", { name: "追加到已有笔记" });
    expect(within(create).getByRole("textbox", { name: "笔记标题" })).toBeInTheDocument();
    expect(within(create).getByRole("button", { name: "新建" })).toBeInTheDocument();
    expect(within(append).getByRole("searchbox", { name: "搜索标题、正文或标签" })).toBeInTheDocument();
    expect(within(append).getByRole("list", { name: "追加到已有笔记" })).toBeInTheDocument();
  });

  it("在标题框里回车就新建,带上所选形状的正文与来源", async () => {
    await open();
    await userEvent.click(screen.getByRole("radio", { name: "带时间戳引用" }));
    await userEvent.type(screen.getByRole("textbox", { name: "笔记标题" }), "访谈摘录{Enter}");
    expect(createNote).toHaveBeenCalledWith("w1", { title: "访谈摘录", markdown: variants[1].markdown, sources: variants[1].sources });
  });
});

describe("已有笔记列表", () => {
  it("有边界、有上限高度、自己滚;回收站里的不列出", async () => {
    await open();
    const list = screen.getByRole("list", { name: "追加到已有笔记" });
    await within(list).findByRole("button", { name: /第一篇/ });
    expect(list.className).toMatch(/\bmax-h-\S+/);
    expect(list.className).toContain("overflow-y-auto");
    expect(list.className).toContain("border");
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(within(list).queryByText("回收站里的")).toBeNull();
  });

  it("每一行有图标、标题和更新时间,点一下就追加到那一篇", async () => {
    await open();
    const row = await screen.findByRole("button", { name: /第一篇/ });
    expect(row.querySelector("svg")).not.toBeNull();
    expect(row).toHaveTextContent("2小时前");
    await userEvent.click(row);
    expect(appendNote).toHaveBeenCalledWith(expect.objectContaining({ id: "n1" }), variants[0].markdown, variants[0].sources);
  });

  it("方向键:搜索框 ↓ 进列表,行间上下走,第一行 ↑ 回到搜索框", async () => {
    await open();
    const first = await screen.findByRole("button", { name: /第一篇/ });
    const second = screen.getByRole("button", { name: /第二篇/ });
    const search = screen.getByRole("searchbox");
    search.focus();
    await userEvent.keyboard("{ArrowDown}");
    expect(first).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");
    expect(second).toHaveFocus();
    await userEvent.keyboard("{Home}");
    expect(first).toHaveFocus();
    await userEvent.keyboard("{ArrowUp}");
    expect(search).toHaveFocus();
  });

  it("一篇都没有时说「还没有笔记」,搜不到时说「没有找到笔记」", async () => {
    vi.mocked(listNotes).mockResolvedValue([] as never);
    await open();
    const list = screen.getByRole("list", { name: "追加到已有笔记" });
    expect(await within(list).findByText("还没有笔记")).toBeInTheDocument();
    await userEvent.type(screen.getByRole("searchbox"), "xyz");
    await waitFor(() => expect(within(list).getByText("没有找到笔记")).toBeInTheDocument());
  });
});
