/** @vitest-environment jsdom */
/**
 * 改笔记(edit_note)的确认卡:不再是一坨 operations JSON。每个操作一块 ——
 * 替换画成「原文 → 新文」的差异(删去的划掉、新加的高亮),插入画出锚点那一截上下文和要插进去的字;
 * 长的先折起来;原始 JSON 还在「原始数据」里。
 */
import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { expect, it, vi } from "vitest";

import type { Confirmation } from "@/api/client";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { ConfirmationCard } from "@/features/agent/ConfirmationCard";

function card(operations: unknown[]): Confirmation {
  return {
    id: "c1",
    workspace_id: "w1",
    session_id: "s1",
    tool: "edit_note",
    writes: ["notes"],
    allow_tool: "edit_note",
    permission: "edit",
    summary: "修改笔记「周报」:替换 1 处、插入 1 处",
    headline: "修改笔记「周报」:替换 1 处、插入 1 处",
    warning: "",
    always_asks: false,
    choices: {},
    summary_key: "confirm_editNote",
    summary_params: {},
    payload: { note_id: "n1", operations, _title: "周报" },
    status: "pending",
    result: {},
    error: null, error_summary: null, error_detail: null, error_hint: null,
    requested_by: "pi-agent",
    decision_mode: "manual",
    decided_by: null,
    created_at: "2026-10-04T00:00:00Z",
    resolved_at: null,
  };
}

const view = (operations: unknown[]) =>
  render(<ConfirmationCard item={card(operations)} eyebrow="智能体请求" actions={<button type="button">允许一次</button>} />);

it("每个操作一块:替换是差异,插入是锚点上下文 + 新字;不再列 operations 的 JSON", () => {
  const { container } = view([
    { kind: "replace", find: "开场的三十秒还是太慢。", text: "开场三十秒节奏偏慢。" },
    { kind: "insert", after: "- 补拍两个产品特写镜头\n- 和配音老师约时间", text: "\n- 把开场压到十五秒以内" },
  ]);

  const blocks = container.querySelectorAll("[data-note-op]");
  expect(blocks).toHaveLength(2);

  const replace = blocks[0];
  expect(replace.getAttribute("data-note-op")).toBe("replace");
  expect(replace.textContent).toContain("confirmNoteReplace");
  expect([...replace.querySelectorAll("del")].map((node) => node.textContent)).toEqual(["的", "还是太"]);
  expect([...replace.querySelectorAll("ins")].map((node) => node.textContent)).toEqual(["节奏偏"]);

  const insert = blocks[1];
  expect(insert.getAttribute("data-note-op")).toBe("insert");
  expect(insert.textContent).toContain("confirmNoteInsertAfter");
  expect(insert.textContent).toContain("和配音老师约时间");
  expect(insert.querySelector("ins")!.textContent).toBe("\n- 把开场压到十五秒以内");

  //: 通用参数表(note_id、operations 那块 JSON)不再摊出来;原始数据还在,一字不少。
  expect(container.querySelector("[data-field='operations']")).toBeNull();
  expect(container.querySelector("dl")).toBeNull();
  const raw = container.querySelector("details pre")!;
  expect(JSON.parse(raw.textContent!).operations).toHaveLength(2);
});

it("把一段换成空 = 删除;插在前面的锚点在新字后面", () => {
  const { container } = view([
    { kind: "replace", find: "多余的一句。", text: "" },
    { kind: "insert", before: "正片开始", text: "片头\n\n" },
  ]);
  const [remove, before] = container.querySelectorAll("[data-note-op]");
  expect(remove.textContent).toContain("confirmNoteDelete");
  expect(remove.querySelector("del")!.textContent).toBe("多余的一句。");
  expect(remove.querySelector("ins")).toBeNull();
  expect(before.textContent).toContain("confirmNoteInsertBefore");
  expect(before.textContent!.indexOf("片头")).toBeLessThan(before.textContent!.indexOf("正片开始"));
});

it("长的先折起来,点开看全文", () => {
  const long = "很长的一段原文。".repeat(120);
  const { container } = view([{ kind: "replace", find: long, text: `${long}补一句。` }]);
  const block = container.querySelector("[data-note-op]")!;
  expect(block.textContent).not.toContain("补一句。");
  fireEvent.click(screen.getByRole("button", { name: "confirmNoteExpand" }));
  expect(block.textContent).toContain("补一句。");
  expect(screen.getByRole("button", { name: "confirmCollapse" })).toBeTruthy();
});
