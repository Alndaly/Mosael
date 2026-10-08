/** @vitest-environment jsdom */
/**
 * 体检 UM-28:起名的弹窗此前只有一个没有标签的空框 —— 新建时得猜要填什么,读屏只念「编辑文本」。
 */
import React from "react";
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { messages, type MessageKey } from "@/app/messages";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: MessageKey) => messages["zh-CN"][key] }));

import { RenameDialog } from "./modals";

it("起名的弹窗有看得见的标签,不给就是「名称」;给了就用给的", () => {
  const view = render(<RenameDialog open title="新建人物" initialValue="" pending={false} onCancel={() => {}} onSubmit={() => {}} />);
  expect(screen.getByRole("textbox", { name: messages["zh-CN"].nameField })).toBeInTheDocument();
  view.unmount();

  render(<RenameDialog open title="新建工作区" label="工作区名称" initialValue="" pending={false} onCancel={() => {}} onSubmit={() => {}} />);
  expect(screen.getByRole("textbox", { name: "工作区名称" })).toBeInTheDocument();
});
