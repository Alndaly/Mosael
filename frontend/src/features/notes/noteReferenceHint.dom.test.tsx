/** @vitest-environment jsdom */

/**
 * 正文里的引用悬停给一块**预览**(标题 + 那一版正文的开头)—— 维护者:「文档内部的引用希望支持鼠标 hover 的时候
 * 能有预览块 Hint」。名字只够认出是哪一篇;要想起"它说的是什么",此前只能点开、翻完、再回来。
 *
 * 这一条同时钉住引用**渲染成一个 `<a data-note-reference>`**(节点视图交给 EditorContent 渲染,
 * 见 editorExtensions 里那条注释),以及悬停时才去问那篇笔记(一篇文档几十个引用,不预判)。
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, expect, it, vi } from "vitest";

import { hoverHint } from "@/test/hint";

vi.mock("@/app/preferences", () => ({
  usePreferences: () => ({ locale: "zh-CN" }),
  useI18n: () => (key: string) => key,
}));

const getNoteReference = vi.hoisted(() => vi.fn());
//: `noteReferenceQuery` 是那个模块里的函数,它自己引的是同模块的 `getNoteReference` —— 只替掉后者的话,
//: 查询里用的还是原来那个(会真发请求、404)。两处一起替。
vi.mock("@/api/domains/notes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/domains/notes")>()),
  getNoteReference,
  noteReferenceQuery: (workspaceId: string, id: string, revision?: number) => ({
    queryKey: ["note-reference-test", workspaceId, id, revision ?? null],
    queryFn: () => getNoteReference(workspaceId, id, revision),
    enabled: Boolean(workspaceId && id),
    retry: false as const,
  }),
}));

import { NoteReader } from "@/features/notes/NoteEditor";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => { vi.clearAllMocks(); });

const REFERENCE = "[@周报](#/notes?note=n1&revision=3)";

function mount(markdown = REFERENCE) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <NoteReader markdown={markdown} workspaceId="ws" />
    </QueryClientProvider>,
  );
}

it("悬停一块引用:出标题 + 那一版正文的开头,并且是悬停时才去问", async () => {
  getNoteReference.mockResolvedValue({
    note_id: "n1", revision: 3, title: "周报",
    markdown: "# 本周\n\n- 完成了 **引用预览**\n- 下周一继续 [链接](https://example.com)",
    tags: [], citation_url: "",
  });
  mount();

  const anchor = await screen.findByText("@周报");
  expect(anchor.tagName, "引用是一个链接(节点视图渲染出来的那个锚)").toBe("A");
  expect(anchor.getAttribute("href")).toBe("#/notes?note=n1&revision=3");
  expect(getNoteReference, "没悬停过就不问 —— 一屏几十个引用不该逐个去拉").not.toHaveBeenCalled();

  const said = await hoverHint(anchor);
  expect(said, "第一行是那一篇的标题").toContain("周报");
  expect(said, "底下是正文开头:Markdown 记号剥掉").toContain("本周");
  expect(said, "列表记号换成点、强调记号去掉").toContain("· 完成了 引用预览");
  expect(said, "链接留字不留地址").toContain("下周一继续 链接");
  expect(said, "钉住的那一版要说出来").toContain("引用的是第 3 版");
  expect(getNoteReference).toHaveBeenCalledWith("ws", "n1", 3);
});

it("引用的那一篇没了:说明里直说,不留一个看着正常的引用", async () => {
  getNoteReference.mockRejectedValue(new Error("404"));
  mount();

  const anchor = await screen.findByText("@周报");
  const said = await hoverHint(anchor);
  expect(said).toContain("「周报」已经不在了");
  expect(said).toContain("它可能已被删除");
});

it("引用不等于当前版本时也说清引用的是哪一版", async () => {
  getNoteReference.mockResolvedValue({ note_id: "n1", revision: 7, title: "周报", markdown: "最新那句", tags: [], citation_url: "" });
  mount("[@周报](#/notes?note=n1)");

  const said = await hoverHint(await screen.findByText("@周报"));
  expect(said).toContain("最新那句");
  expect(said, "没有钉版本:不提版本").not.toContain("引用的是第");
  await waitFor(() => expect(getNoteReference).toHaveBeenCalledWith("ws", "n1", undefined));
});
