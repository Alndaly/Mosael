/** @vitest-environment jsdom */
import React from "react";
import { act, cleanup, render, waitFor } from "@testing-library/react";
import type { Editor, JSONContent } from "@tiptap/react";
import { afterEach, expect, it, vi } from "vitest";

/**
 * 智能体输入框里打 `@`,菜单开着时**渲染要停得下来**。
 *
 * 此前 `@` 菜单的可见列表由一个行内箭头函数过滤(每次渲染都换身份),`useSuggestionMenu` 跟着它重算、每次又回一个新对象 ——
 * 「渲染 → effect → setState → 渲染」转个不停:打一个 `@`,两秒多就是七十多条 Maximum update depth exceeded,
 * AI Studio 和各页面的助手面板(同一个组件)一起中招。这里数菜单打开之后的提交次数,并盯住控制台没有那句话。
 */

vi.mock("@/app/preferences", async () => {
  const { messages } = await import("@/app/messages");
  return { useI18n: () => (key: keyof (typeof messages)["zh-CN"]) => messages["zh-CN"][key] ?? key };
});
vi.mock("@/api/client", () => ({ assetThumbnailUrl: (id: string) => `/thumb/${id}`, listSkills: async () => [] }));
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
import type { AgentReference } from "@/features/agent/references";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const NOTES: AgentReference[] = [
  { kind: "note", id: "n1", name: "第二篇笔记" },
  { kind: "note", id: "n2", name: "第三篇笔记" },
];

it("菜单开着时只渲染有限几次,控制台没有 Maximum update depth exceeded", async () => {
  const errors = vi.spyOn(console, "error").mockImplementation(() => {});
  let commits = 0;
  function Harness() {
    const [value, setValue] = React.useState<JSONContent>(emptyDocument);
    return (
      <React.Profiler
        id="composer"
        onRender={() => {
          commits += 1;
          //: 死循环时当场炸,而不是把测试进程拖到内存耗尽。
          if (commits > 200) throw new Error("render loop: the composer never stops re-rendering");
        }}
      >
        <ChatComposer workspaceId="ws-1" value={value} onChange={setValue} onSubmit={() => {}} search={async () => NOTES} />
      </React.Profiler>
    );
  }
  const view = render(<Harness />);
  const editor = (view.container.querySelector(".ProseMirror") as HTMLElement & { editor?: Editor }).editor as Editor;
  await act(async () => {
    editor.commands.focus("end");
    editor.commands.insertContent("看看 @");
  });
  await waitFor(() => expect(document.querySelector("[data-suggestion-menu]")?.textContent).toContain("第二篇笔记"));
  const opened = commits;
  // 菜单开着,什么都不做,再等一会儿:不该自己一直重渲。
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 300));
  });
  expect(commits - opened, "菜单开着、没有任何输入时还在重渲").toBeLessThanOrEqual(2);
  const loops = errors.mock.calls.filter((args) => String(args[0]).includes("Maximum update depth"));
  expect(loops).toHaveLength(0);
});

it("输入区有可访问名称:读屏念得出这是给智能体写的消息", async () => {
  const { screen } = await import("@testing-library/react");
  function Harness() {
    const [value, setValue] = React.useState<JSONContent>(emptyDocument);
    return <ChatComposer workspaceId="ws-1" value={value} onChange={setValue} onSubmit={() => {}} search={async () => []} />;
  }
  render(<Harness />);
  expect(screen.getByRole("textbox", { name: "给智能体的消息" })).toBeTruthy();
});
