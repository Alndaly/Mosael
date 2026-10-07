/**
 * 笔记页的助手面板由装配那一侧交进去(笔记不 import 助手,见 NotesView 的 NotesAgentPanelProps 和 agent/NotesWithAgent)。
 * 漏交的话笔记页上的开关和「问 AI」都不出现 —— 不报错,只是功能静默地没了,所以钉一下:笔记页渲染的是装上了助手的那一份。
 */
import type React from "react";
import { expect, it } from "vitest";
import { PAGE_RENDERERS, type PageContext } from "./pages";

it("笔记页是装上了助手的那一份", async () => {
  const page = PAGE_RENDERERS.notes({ workspace: { id: "ws" } } as PageContext) as React.ReactElement;
  const lazy = page.type as unknown as { _payload: { _result: () => Promise<{ default: unknown }> } };
  const { NotesWithAgent } = await import("@/features/agent/NotesWithAgent");
  expect((await lazy._payload._result()).default).toBe(NotesWithAgent);
});
