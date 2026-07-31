/** @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { describe, expect, it, vi } from "vitest";

/**
 * 授权流程里「一步提问」的渲染。
 *
 * 真实回归:Codex 的第一步是 select(浏览器授权 / 设备码),而这里最初把所有提问都渲染成
 * 文本框 —— 用户看到的是一个**空输入框**,得凭空猜出 "browser" 这个内部 id 才能往下走,
 * 界面上没有任何地方提到过它。授权就此卡死,且不报任何错。
 *
 * 判据有两条,缺一不可:选项要显示出来(用 label),提交的要是 **id**(不是 label)。
 * 只测"显示出来了"会漏掉后半条 —— 提交 label 一样会让授权失败,只是失败在更远的地方。
 */

vi.mock("@/app/preferences", () => ({ useI18n: () => (k: string) => k, usePreferences: () => ({ locale: "zh-CN" }) }));

import { AuthPromptField } from "@/features/settings/ProviderOAuthDialog";

const selectPrompt = {
  prompt_id: "p1",
  prompt_type: "select",
  message: "Select OpenAI Codex login method:",
  placeholder: "",
  options: [
    { id: "browser", label: "Browser login (default)" },
    { id: "device_code", label: "Device code login (headless)", description: "无头环境用" },
  ],
} as never;

describe("授权提问", () => {
  it("select 类型把选项摆出来,点击提交的是选项 id", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(<AuthPromptField prompt={selectPrompt} submitLabel="提交" onSubmit={onSubmit} />);

    expect(screen.getByText("Select OpenAI Codex login method:")).toBeTruthy();
    // 空输入框就是那次回归的样子:有输入框 = 又把 select 当文本问了。
    expect(document.querySelector("input")).toBeNull();

    await user.click(screen.getByText("Browser login (default)"));
    expect(onSubmit).toHaveBeenCalledWith("browser");
  });

  it("选项的补充说明会显示(有的选项只有描述能说清区别)", () => {
    render(<AuthPromptField prompt={selectPrompt} submitLabel="提交" onSubmit={vi.fn()} />);
    expect(screen.getByText("无头环境用")).toBeTruthy();
  });

  it("文本类型仍然是输入框,提交输入的内容", async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();
    render(
      <AuthPromptField
        prompt={{ prompt_id: "p2", prompt_type: "manual_code", message: "粘贴授权码", placeholder: "", options: [] } as never}
        submitLabel="提交"
        onSubmit={onSubmit}
      />,
    );
    await user.type(screen.getByRole("textbox"), "  code-123  ");
    await user.click(screen.getByText("提交"));
    expect(onSubmit).toHaveBeenCalledWith("code-123");
  });

  it("secret 类型不明文显示 —— 这一步填的是可直接换取令牌的东西", () => {
    render(
      <AuthPromptField
        prompt={{ prompt_id: "p3", prompt_type: "secret", message: "API Key", placeholder: "", options: [] } as never}
        submitLabel="提交"
        onSubmit={vi.fn()}
      />,
    );
    expect(document.querySelector("input")?.getAttribute("type")).toBe("password");
  });
});
