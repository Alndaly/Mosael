/** @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) =>
    ({
      wfAgentSessions: "会话",
      chatNewSession: "新对话",
      chatSearchSessions: "搜索对话…",
      chatSearchNoMatch: "没有匹配的对话",
      delete: "删除",
    })[key] ?? key,
}));

import { AgentSessionSwitcher } from "./AgentSessionSwitcher";

const sessions = [
  { id: "one", title: "一个非常非常长的会话标题，需要在窗口标题处省略" },
  { id: "two", title: "浏览器清理" },
  { id: "three", title: "时间线粗剪" },
];

describe("AgentSessionSwitcher", () => {
  it("左上角直接显示当前会话名且标题入口没有外框", () => {
    render(
      <AgentSessionSwitcher
        sessions={sessions}
        activeSession={sessions[0]}
        deleting={false}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    const trigger = screen.getByRole("button", { name: "会话" });
    expect(trigger).toHaveTextContent(sessions[0].title);
    expect(trigger).toHaveClass("border-0", "bg-transparent");
    expect(trigger).toHaveClass("w-full");
    expect(trigger.querySelector("span")).toHaveClass("truncate");
  });

  it("可以搜索并切换会话", async () => {
    const onSelect = vi.fn();
    render(
      <AgentSessionSwitcher
        sessions={sessions}
        activeSession={sessions[0]}
        deleting={false}
        onSelect={onSelect}
        onDelete={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "会话" }));
    const search = screen.getByRole("searchbox", { name: "搜索对话…" });
    await userEvent.type(search, "时间线");

    expect(screen.getByText("时间线粗剪")).toBeVisible();
    expect(screen.queryByText("浏览器清理")).toBeNull();
    await userEvent.click(screen.getByText("时间线粗剪"));
    expect(onSelect).toHaveBeenCalledWith("three");
    expect(screen.queryByRole("searchbox", { name: "搜索对话…" })).toBeNull();
  });

  it("搜索无结果时给出明确空状态", async () => {
    render(
      <AgentSessionSwitcher
        sessions={sessions}
        activeSession={sessions[0]}
        deleting={false}
        onSelect={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "会话" }));
    await userEvent.type(screen.getByRole("searchbox", { name: "搜索对话…" }), "不存在");
    expect(screen.getByText("没有匹配的对话")).toBeVisible();
  });
});
