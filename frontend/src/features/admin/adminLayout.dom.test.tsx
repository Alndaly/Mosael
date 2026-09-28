/** @vitest-environment jsdom */
import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CONTROL_HEIGHT } from "@/components/ui/control-size";
import { ADMIN_CARD, AdminRow, AdminRowNote, AdminRowState, AdminTag } from "./adminLayout";

/**
 * 管理页只有一种行。引擎、模型这类「一个东西」的行用的是 AdminRow 的几个插槽,而不是另一种行 ——
 * 它们从设置页搬来时带着 SettingsItemRow(20px 行距、text-ui-md 标签),和管理页其余的行不是一个刻度。
 */
describe("AdminRow 的插槽", () => {
  it("元信息贴着名字、假值跳过;说明、控件各在各的位置", () => {
    const { container } = render(
      <div className={ADMIN_CARD}>
        <AdminRow label="出站代理">
          <input aria-label="代理" />
        </AdminRow>
        <AdminRow label="FunASR" meta={["funasr", null, "973 MB"]} description="中文好">
          <button type="button">下载</button>
        </AdminRow>
      </div>,
    );

    const rows = container.querySelectorAll("[data-admin-row]");
    expect(rows).toHaveLength(2);
    // 同一张卡里的两行同一个刻度:引擎行不是另一种行高。
    expect(rows[1].className).toBe(rows[0].className);
    const meta = rows[1].querySelector("[data-admin-row-meta]")!;
    expect(meta).toHaveTextContent("funasr · 973 MB");
    expect(meta).toHaveClass("text-ui-xs", "text-muted-foreground");
    expect(rows[1].querySelector("[data-admin-row-description]")).toHaveTextContent("中文好");
    expect(screen.getByRole("button", { name: "下载" }).parentElement).toHaveAttribute("data-admin-row-control");
    // 没有元信息的行不留那一格。
    expect(rows[0].querySelector("[data-admin-row-meta]")).toBeNull();
  });

  it("状态行在说明下面、和说明同一档字号;进度横贯整行", () => {
    const { container } = render(
      <AdminRow label="Demucs" notes={<AdminRowNote tone="destructive">pip 失败</AdminRowNote>} footer={<div>进度</div>} />,
    );

    const note = screen.getByText("pip 失败");
    expect(note).toHaveAttribute("data-admin-row-note");
    expect(note).toHaveClass("text-destructive", "text-ui-xs");
    const footer = container.querySelector("[data-admin-row-footer]")!;
    expect(footer).toHaveTextContent("进度");
    expect(footer).toHaveClass("basis-full");
    // 没有右边的控件就不留那一格。
    expect(container.querySelector("[data-admin-row-control]")).toBeNull();
  });

  it("右边的状态和它替换掉的 sm 按钮一样高 —— 从「下载」变成「已安装」时整行不跳", () => {
    render(
      <AdminRow label="F5-TTS">
        <AdminRowState tone="success">已安装</AdminRowState>
      </AdminRow>,
    );

    expect(screen.getByText("已安装")).toHaveClass(CONTROL_HEIGHT.sm, "text-success");
  });

  it("标签是安静的:淡底、不描边、不大写", () => {
    render(<AdminTag tone="warning">会去掉音乐</AdminTag>);
    const tag = screen.getByText("会去掉音乐");
    expect(tag).toHaveClass("rounded-full", "text-warning");
    expect(tag).not.toHaveClass("border");
    expect(tag).not.toHaveClass("uppercase");
  });
});
