/** @vitest-environment jsdom */
import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { expect, it, vi } from "vitest";

/**
 * 智能体「全部工具」里的一行。工具说明是写给模型看的 MCP docstring,插件工具还带着清单里的
 * `**强调**` —— 按格式渲染,点开看全文时同样不露记号。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { ToolBrowserRow } from "@/features/ai-studio/ChatWorkspace";

it("工具说明里的记号渲染成格式,按钮里不套链接", () => {
  const tool = {
    name: "plugin__oss_upload",
    description: "[插件·OSS] 交回一条**限时直链**,传给 `reference_video`。见 [文档](https://example.com)",
    parameters: { type: "object", properties: {} },
    confirmation: false,
  };
  const { container } = render(<ToolBrowserRow tool={tool as never} />);
  expect(screen.getByText("限时直链").tagName).toBe("STRONG");
  expect(screen.getByText("reference_video").tagName).toBe("CODE");
  expect(container.querySelector("button a")).toBeNull();
  fireEvent.click(container.querySelector("button")!);
  expect(container.textContent).not.toMatch(/\*\*|`|\]\(/);
});
