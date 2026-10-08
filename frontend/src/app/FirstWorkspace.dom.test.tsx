/** @vitest-environment jsdom */
/**
 * 体检 UM-10:第一个工作区此前不给起名,每个新用户的都叫「默认工作区」—— 被拉进团队后切换器里两行同名。
 */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => (key === "workspaceDefaultFor" ? "{name}的工作区" : key),
}));
vi.mock("@/app/auth", () => ({ useAuth: () => ({ user: { id: "u1", username: "mate", display_name: "小美" } }) }));

import { FirstWorkspace } from "./FirstWorkspace";

it("第一个工作区预填「{昵称}的工作区」,可以改名再建", () => {
  const onCreate = vi.fn();
  render(<FirstWorkspace pending={false} onCreate={onCreate} />);
  const name = screen.getByRole("textbox", { name: "workspaceNameLabel" });
  expect(name).toHaveValue("小美的工作区");
  fireEvent.change(name, { target: { value: "  剪辑组  " } });
  fireEvent.click(screen.getByRole("button", { name: /createWorkspace/ }));
  expect(onCreate).toHaveBeenCalledWith("剪辑组");

  fireEvent.change(name, { target: { value: "   " } });
  expect(screen.getByRole("button", { name: /createWorkspace/ })).toBeDisabled();
});
