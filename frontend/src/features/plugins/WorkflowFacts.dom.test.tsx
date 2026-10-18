/** @vitest-environment jsdom */

/**
 * 工作流详情里的那几节(WorkflowFacts):「用到的模型」「缺的节点」「缺的模型」共用一种行(FactLine)。
 *
 * 维护者截图:用到的模型那几行,文件名 / 目录后面空出一大段,「缺」徽标被推到行尾,又没有和下面「缺的模型」的
 * 「下载」按钮对上。原因在 FactLine:名字那一列 `flex-1` 把目录顶到最右边,状态徽标是那一列外面的兄弟,正好落在
 * 行尾那一格动作前面 —— 看着像一列,其实和「下载」的右缘差着那一格的宽。
 *
 * 现在名字 / 目录 / 状态挨着排:名字放不下时截断(悬停看全文),目录和徽标 `shrink-0`,不会把行撑出横向滚动。
 * 真正对成一列的是动作(跳到模型库、装上、下载),它们照旧在行尾那一格里;状态不占那一格。
 *
 * jsdom 没有排版、量不了宽,所以这里按容器结构判(和 design/truncateNeedsShrinkableBox 同一种做法)。
 */

import React from "react";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh" }),
}));

import type { WorkflowFile } from "@/api/client";
import { hoverHint } from "@/test/hint";

import { WorkflowFacts } from "./WorkflowFacts";

afterEach(cleanup);

type Facts = Pick<WorkflowFile, "models" | "missing_nodes" | "missing_models">;

const MISSING_URL = "https://huggingface.co/x/y/resolve/main/gone.safetensors";

function facts(overrides: Partial<Facts> = {}): Facts {
  return {
    models: [
      { folder: "checkpoints", name: "sdxl.safetensors", present: true },
      { folder: "loras", name: "gone.safetensors", present: false },
    ],
    missing_nodes: [],
    missing_models: [{ folder: "loras", name: "gone.safetensors", url: MISSING_URL, hash: "", hash_type: "" }],
    ...overrides,
  };
}

function renderFacts(overrides: Partial<Facts> = {}) {
  return render(<WorkflowFacts facts={facts(overrides)} onShowModel={vi.fn()} />);
}

/** 一节里含某段文字的那一行。 */
function rowOf(region: HTMLElement, text: string): HTMLElement {
  return within(region).getByText(text).closest("li") as HTMLElement;
}

function lineOf(element: HTMLElement): HTMLElement | null {
  return element.closest<HTMLElement>("[data-fact-line]");
}

const used = () => screen.getByRole("region", { name: "workflowModels" });
const missing = () => screen.getByRole("region", { name: "workflowMissingModels" });

describe("用到的模型:名字 / 目录 / 状态挨着排", () => {
  it("「缺」徽标紧跟在目录名后面,不推到行尾", () => {
    renderFacts();
    const row = rowOf(used(), "gone.safetensors");
    const name = within(row).getByText("gone.safetensors");
    const folder = within(row).getByText("loras");
    const badge = within(row).getByText("workflowModelMissing");

    //: 目录名和徽标在同一个行内容器里 —— 不是「名字一列把目录顶到右边,徽标再挂在外面」。
    const line = lineOf(folder);
    expect(line, "目录和徽标要在同一个行内容器里").toBeTruthy();
    expect(line!.contains(badge), "徽标和目录在同一个行内容器里").toBe(true);
    //: 徽标紧挨着目录(相邻兄弟),不是被 justify-between / flex-1 推到行尾。
    expect(badge.previousElementSibling, "徽标紧挨着目录名").toBe(folder);
    expect(name.className, "名字不撑满那一行,目录和徽标才不会被顶到右边").not.toContain("flex-1");
    expect(line!.className).not.toContain("justify-between");
    //: 徽标不是动作,不占行尾那一格。
    expect(badge.closest("[data-fact-slot]")).toBeNull();
  });

  it("超长文件名:名字那格截断,徽标还在原位,整行可以收缩(没有横向滚动)", async () => {
    const LONG = "sdxl-refiner-illustration-community-final-final-v3-repacked-fp16.safetensors";
    renderFacts({ models: [{ folder: "checkpoints", name: LONG, present: false }] });
    const row = rowOf(used(), LONG);
    const name = within(row).getByText(LONG);
    const folder = within(row).getByText("checkpoints");
    const badge = within(row).getByText("workflowModelMissing");

    //: 截断走 Truncate:单行省略号,全文一直在 DOM 里(悬停 / 读屏看的是同一份)。
    expect(name.className).toContain("truncate");
    expect(name.className).toContain("min-w-0");
    expect(name.textContent).toBe(LONG);

    //: 从名字到行,每一层都能收缩;压的是名字自己,不会把整行撑出横向滚动。
    const line = name.parentElement!;
    expect(line.hasAttribute("data-fact-line"), "名字和目录在同一行").toBe(true);
    expect(line.className).toContain("flex");
    expect(line.className).toContain("min-w-0");
    const column = line.parentElement!;
    expect(column.className).toContain("min-w-0");
    expect(column.className).toContain("flex-1");
    const rowBox = column.parentElement!;
    expect(rowBox.className).toContain("flex");
    expect(rowBox.className).toContain("min-w-0");

    //: 名字长不把目录 / 徽标挤走:名字后面就是目录,目录后面就是徽标。
    expect(name.nextElementSibling).toBe(folder);
    expect(folder.nextElementSibling).toBe(badge);
    expect(line.contains(badge)).toBe(true);

    //: 真被截断时,悬停看得到全文(量法照 components/ui/truncate.dom.test.tsx)。
    Object.defineProperty(name, "scrollWidth", { value: 900, configurable: true });
    Object.defineProperty(name, "clientWidth", { value: 120, configurable: true });
    expect(await hoverHint(name)).toBe(LONG);
  });

  it("和「缺的模型」同一个节奏;对成一列的是动作,不是徽标", () => {
    renderFacts();
    const usedRow = rowOf(used(), "sdxl.safetensors");
    const missingRow = rowOf(missing(), "gone.safetensors");
    const usedLine = lineOf(within(usedRow).getByText("checkpoints"))!;
    const missingLine = lineOf(within(missingRow).getByText("loras"))!;

    //: 两块的主行是同一种排法:名字 / 目录挨着排,不靠 justify-between 往两头撑。
    expect(usedLine.className).toBe(missingLine.className);
    expect(usedLine.className).not.toContain("justify-between");

    //: 真正共享的那一列是动作:「在模型库里看」和「下载」在同一个 action 格里、同一个右边界。
    const icon = within(usedRow).getByRole("button", { name: "workflowShowInModelLibrary" });
    const download = within(missingRow).getByRole("button", { name: "workflowDownloadInModelLibrary" });
    const iconSlot = icon.closest<HTMLElement>("[data-fact-slot]")!;
    const downloadSlot = download.closest<HTMLElement>("[data-fact-slot]")!;
    expect(iconSlot.className).toBe(downloadSlot.className);
    expect(iconSlot.className).toContain("justify-end");
  });
});
