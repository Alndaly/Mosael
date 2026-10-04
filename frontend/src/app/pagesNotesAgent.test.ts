/**
 * 笔记页的助手面板由页面装配层交进去(笔记不 import 助手,见 NotesView 的 NotesAgentPanelProps)。
 * 漏交的话笔记页上的开关和「问 AI」都不出现 —— 不报错,只是功能静默地没了,所以钉一下。
 */
import type React from "react";
import { expect, it } from "vitest";
import { PAGE_RENDERERS, type PageContext } from "./pages";

it("笔记页拿到了助手面板", () => {
  const page = PAGE_RENDERERS.notes({ workspace: { id: "ws" } } as PageContext) as React.ReactElement<{ AgentPanel?: unknown }>;
  expect(page.props.AgentPanel).toBeTruthy();
});
