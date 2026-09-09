/** @vitest-environment jsdom */
import React from "react";
import { FileText } from "lucide-react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => ({ close: "移除", composerUploading: "上传中" })[key] ?? key,
}));

import { ComposerChips, type ComposerChip } from "./ComposerChips";

const chip = (extra: Partial<ComposerChip>): ComposerChip => ({
  id: "c",
  label: "一个东西",
  icon: <FileText size={11} />,
  onRemove: vi.fn(),
  ...extra,
});

describe("输入框里那排东西", () => {
  it("附件和笔记引用在同一排 —— 它们回答的是同一个问题", () => {
    /*
     * 此前附件在输入卡**外面**、笔记引用在里面,两处的小条还各写了一份样式。可用户看到的是
     * "我这条消息里带了什么" —— 一件事,不该有两个地方、两种长相。
     */
    render(
      <ComposerChips
        chips={[
          chip({ id: "a", label: "IMG_1353.PNG", thumbnail: "/thumb/a" }),
          chip({ id: "n", label: "mosael", text: { title: "mosael", body: "笔记正文" } }),
        ]}
      />,
    );
    const row = screen.getByTitle("IMG_1353.PNG").parentElement;
    expect(row).toBe(screen.getByTitle("mosael").parentElement);
  });

  it("有画面的给缩略图,没有的给图标", () => {
    render(<ComposerChips chips={[chip({ id: "a", label: "图", thumbnail: "/thumb/a" }), chip({ id: "f", label: "文件" })]} />);
    expect(screen.getByTitle("图").querySelector("img")).toHaveAttribute("src", "/thumb/a");
    expect(screen.getByTitle("文件").querySelector("img")).toBeNull();
    expect(screen.getByTitle("文件").querySelector("svg")).toBeTruthy();
  });

  it("点开看得到内容 —— 带上去的是什么,发之前能确认", async () => {
    render(<ComposerChips chips={[chip({ label: "script.txt", text: { title: "script.txt", body: "第一幕" } })]} />);
    await userEvent.click(screen.getByRole("button", { name: "script.txt" }));
    expect(await screen.findByText("第一幕")).toBeInTheDocument();
  });

  it("媒体交给全局灯箱 —— 那里有翻页、Esc 和层级,不必再造一个", async () => {
    const onOpen = vi.fn();
    render(<ComposerChips chips={[chip({ label: "shot.png", thumbnail: "/t", onOpen })]} />);
    await userEvent.click(screen.getByRole("button", { name: "shot.png" }));
    expect(onOpen).toHaveBeenCalled();
  });

  it("点不开的就不给按下去的样子", () => {
    render(<ComposerChips chips={[chip({ label: "音频" })]} />);
    expect(screen.getByRole("button", { name: "音频" })).toBeDisabled();
  });

  it("移除是独立的一个按钮,不是按钮套按钮", async () => {
    const onRemove = vi.fn();
    render(<ComposerChips chips={[chip({ label: "文件", onRemove })]} />);
    // 按钮嵌套是非法 HTML,浏览器会把它拆开,键盘走到哪个都不确定。
    await userEvent.click(screen.getByRole("button", { name: "移除 文件" }));
    expect(onRemove).toHaveBeenCalled();
  });
});
