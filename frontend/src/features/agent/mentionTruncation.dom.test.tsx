/** @vitest-environment jsdom */
import React from "react";
import { act, cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import type { Editor, JSONContent } from "@tiptap/react";
import { afterEach, expect, it, vi } from "vitest";

/**
 * `@` 菜单摆不下的时候**不许一声不吭**。
 *
 * 实测(默认工作区,空查询):素材匹配 312 条、笔记 15、画板 14、工作流 2,而菜单每类只摆 3 条 ——
 * 11 条之后什么都没有,底部一个字都没有。用户原话:「仅显示三个且没有提醒文案这个设计极其让人疑惑」。
 *
 * 盯三件事:摆不下时底部如实说「还有 N 个」(N 是**匹配数**,不是取回来的条数;素材那类 312 份
 * 只取回 6 条);摆得下时一个字的废话都不要有;上下键走到这一屏之外时,选中的那一条要跟着滚 ——
 * 否则"选中的"和"看得见的"不是同一条。
 */

vi.mock("@/app/preferences", async () => {
  const { messages } = await import("@/app/messages");
  return { useI18n: () => (key: keyof (typeof messages)["zh-CN"]) => messages["zh-CN"][key] ?? key };
});
vi.mock("@/api/client", () => ({
  assetThumbnailUrl: (id: string) => `/thumb/${id}`,
  listSkills: async () => [],
  //: **整条链要一起钉住**:菜单底部那行读的是 `searchReferences` 交回来的真数,而不是它摆出来的条数。
  //: 素材按 limit 取回(6 条),匹配数只在 total 里(42 份)。
  listAssetPage: async ({ limit }: { limit: number }) => ({
    items: Array.from({ length: limit }, (_, i) => ({ id: `asset${i}`, name: `asset-${i}`, original_filename: "" })),
    next_cursor: "more",
    total: 42,
  }),
  listBoards: async () => Array.from({ length: 3 }, (_, i) => ({ id: `board${i}`, name: `board-${i}` })),
  listWorkflows: async () => [],
}));
vi.mock("@/api/domains/notes", () => ({
  listNotes: async () => Array.from({ length: 5 }, (_, i) => ({ id: `note${i}`, title: `note-${i}` })),
}));
vi.mock("@/features/agent/useReferencePreview", () => ({ useReferencePreview: () => ({ open: vi.fn(), modal: null }) }));
vi.mock("@floating-ui/dom", () => ({
  offset: vi.fn(),
  flip: vi.fn(),
  shift: vi.fn(),
  autoUpdate: (_reference: unknown, _element: unknown, update: () => void) => {
    update();
    return () => {};
  },
  computePosition: () => Promise.resolve({ x: 10, y: 10 }),
}));

import { ChatComposer, emptyDocument } from "@/features/agent/ChatComposer";
import { REFERENCE_KIND_LIMIT, type AgentReference, type ReferenceCandidates } from "@/features/agent/references";

const many = (kind: AgentReference["kind"], n: number): AgentReference[] =>
  Array.from({ length: n }, (_, i) => ({ kind, id: `${kind}${i}`, name: `${kind}-${i}` }));

/** 交回来的那一份:每类恰好封顶(和 searchReferences 摆得下的一样多)。 */
const SHOWN: AgentReference[] = [
  ...many("asset", REFERENCE_KIND_LIMIT),
  ...many("note", REFERENCE_KIND_LIMIT),
  ...many("board", REFERENCE_KIND_LIMIT),
];

/** 匹配到的真数:素材 312(服务端 total 数的),其余三类是整份取回之后数的。 */
const CROWDED: ReferenceCandidates = {
  items: SHOWN,
  matched: { asset: 312, note: 15, board: 14, workflow: 2 },
};

/** 一共 343 条匹配,摆出来 18 条 → 还有 325 条没摆出来。 */
const HIDDEN = 312 + 15 + 14 + 2 - SHOWN.length;

const FEW: ReferenceCandidates = {
  items: many("note", 2),
  matched: { asset: 0, note: 2, board: 0, workflow: 0 },
};

async function openMenu(search?: () => Promise<ReferenceCandidates>) {
  function Harness() {
    const [value, setValue] = React.useState<JSONContent>(emptyDocument);
    return <ChatComposer workspaceId="ws-1" value={value} onChange={setValue} onSubmit={() => {}} search={search} />;
  }
  const view = render(<Harness />);
  const editor = (view.container.querySelector(".ProseMirror") as HTMLElement & { editor?: Editor }).editor as Editor;
  await act(async () => {
    editor.commands.focus("end");
    editor.commands.insertContent("看看 @");
  });
  await waitFor(() => expect(document.querySelectorAll("[data-suggestion-menu] [role='option']").length).toBeGreaterThan(0));
  return { editor, menu: document.querySelector<HTMLElement>("[data-suggestion-menu]")! };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("匹配多于上限:底部如实说「还有 N 个」,N 按匹配数算而不是取回来的条数", async () => {
  const { menu } = await openMenu(async () => CROWDED);
  expect(menu.querySelectorAll("[role='option']")).toHaveLength(SHOWN.length);
  //: 素材那一类只取回 6 条,而匹配数写在服务端的 total 里:说 312 才是实话,说 6 就等于没说。
  expect(menu.textContent).toContain(`还有 ${HIDDEN} 个`);
});

it("匹配少于上限:那行提示一个字都不出现", async () => {
  const { menu } = await openMenu(async () => FEW);
  expect(menu.querySelectorAll("[role='option']")).toHaveLength(2);
  expect(menu.textContent).not.toContain("还有");
});

it("整条链:默认那份候选(searchReferences)交回的真数就是底部说的数", async () => {
  //: 不给 `search=` —— 走真的那一条:素材 42 份(只取回 6 条)、笔记 5、画板 3,摆出来 14 条,还有 36 条。
  const { menu } = await openMenu();
  expect(menu.querySelectorAll("[role='option']")).toHaveLength(6 + 5 + 3);
  expect(menu.textContent).toContain("还有 36 个");
});

it("引用笔记这条能力还在 `@` 菜单里:挑一条笔记,落成 kind=note 的引用", async () => {
  //: 输入框下面那个「引用笔记」按钮去掉了(见 composerNoteEntry.dom.test.tsx),能力走这里 —— 少一个入口,
  //: 不是少一样能力。挑中的那一条要落成引用节点(发送时它的 id 走结构化字段给后端)。
  const { editor, menu } = await openMenu();
  expect(menu.textContent).toContain("笔记");
  const option = [...menu.querySelectorAll<HTMLElement>("[role='option']")].find((one) => one.textContent?.includes("note-1"))!;
  await act(async () => {
    fireEvent.click(option);
  });
  const refs = (editor.getJSON().content ?? [])
    .flatMap((block) => block.content ?? [])
    .filter((node) => node.type === "agentRef")
    .map((node) => (node as { attrs?: unknown }).attrs);
  expect(refs).toEqual([{ kind: "note", refId: "note1", name: "note-1" }]);
});

it("上下键跨过截断边界:选中的那一条跟着滚进视野,回车选中它", async () => {
  const scrolled = vi.fn();
  const original = Element.prototype.scrollIntoView;
  Element.prototype.scrollIntoView = scrolled;
  try {
    const { editor, menu } = await openMenu(async () => CROWDED);
    //: 第 15 条(画板那一组的第 4 条)远在 360px 那一屏之外 —— 正是"眼睛跟丢了"的那一段。
    const target = SHOWN[15];
    const dom = editor.view.dom;
    await act(async () => {
      for (let i = 0; i < 15; i += 1) fireEvent.keyDown(dom, { key: "ArrowDown" });
    });
    const active = menu.querySelector("[aria-selected='true']")!;
    expect(active.textContent).toContain(target.name);
    expect(scrolled.mock.contexts, "高亮走到屏幕外了,却没有把这一条滚进视野").toContain(active);

    await act(async () => {
      fireEvent.keyDown(dom, { key: "Enter" });
    });
    //: 回车仍然是"选中高亮的那一条"(上下键的行为没变),落成正文里的引用胶囊。
    await waitFor(() => expect(editor.getText()).toContain(target.name));
  } finally {
    Element.prototype.scrollIntoView = original;
  }
});
