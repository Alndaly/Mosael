/** @vitest-environment jsdom */
import * as React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { messages, type MessageKey } from "@/app/messages";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { boardAddCatalog } from "@/features/boards/boardTools";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: MessageKey) => messages["zh-CN"][key] }));

const t = (key: MessageKey) => messages["zh-CN"][key];

function openMenu(): HTMLElement[] {
  render(
    <SearchableSelect
      value=""
      onValueChange={vi.fn()}
      options={boardAddCatalog(t).map(({ icon: Icon, ...one }) => ({ ...one, icon: <Icon /> }))}
      trigger={<button type="button">添加</button>}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "添加" }));
  return [...document.querySelectorAll<HTMLElement>("[cmdk-item]")];
}

/** 一行的名字和说明:SearchableSelect 把它们排成文字列里的两行。 */
function lines(row: HTMLElement): string[] {
  const column = row.querySelector(":scope > span:not([aria-hidden])");
  return [...(column?.children ?? [])].map((one) => one.textContent ?? "");
}

describe("画板「添加」单子:只有格子,每一行都是图标、名字、一句说明", () => {
  beforeAll(() => {
    vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
    Element.prototype.scrollIntoView ??= () => {};
  });

  it("十种放法,没有工具那一组 —— 把内容变成新内容的事是格子自己的能力", () => {
    const rows = openMenu();
    expect(rows).toHaveLength(10);
    for (const row of rows) {
      const [label, description] = lines(row);
      expect(label, "每一行都有名字").toBeTruthy();
      expect(description, `「${label}」这一行没有说明`).toBeTruthy();
      expect(description).not.toBe(label);
      //: 图标一样大、一样的颜色:都在同一个图标槽里。
      expect(row.querySelector(":scope > span[aria-hidden] svg"), `「${label}」这一行没有图标`).not.toBeNull();
    }
    //: 组名是动词(ADR 0025 决定 6),按生成 / 从素材库 / 引用 / 整理排。
    const groups = [...document.querySelectorAll("[cmdk-group-heading]")].map((one) => one.textContent);
    expect(groups).toEqual(["生成", "从素材库", "引用", "整理"]);
  });

  it("格子那几行是给创作者的一句话(和拉线菜单同一份)", () => {
    const byLabel = Object.fromEntries(openMenu().map((row) => lines(row) as [string, string]));
    expect(byLabel["图片"]).toBe("写一句话生成，或从素材库挑一张");
    expect(byLabel["视频"]).toBe("写一句话、或接一张图生成视频");
    expect(byLabel["音频"]).toBe("配音、音乐或音效");
    expect(byLabel["便签"]).toBe("随手写，或让 AI 写");
    expect(byLabel["文档"]).toBe("引用一篇笔记");
    expect(byLabel["3D 场景"]).toBe("引用一个 3D 场景");
    expect(byLabel["分组"]).toBe("把几格圈在一起");
  });

  it("说明截在一行里(省略号),不把行撑高", () => {
    for (const row of openMenu()) {
      const description = row.querySelector(":scope > span:not([aria-hidden]) > span:nth-child(2)");
      expect(description?.className).toContain("truncate");
    }
  });
});
