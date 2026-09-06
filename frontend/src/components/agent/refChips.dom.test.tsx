/** @vitest-environment jsdom */

/**
 * 智能体交出的那些引用标签得**点得动**。
 *
 * 此前一律是静态的:跑完一个工作流,你拿到的是 `任务 c5d80984cd05` —— 一串截断的 UUID,
 * 点不了、也拼不回完整 id,想看它跑得怎么样只能自己去任务中心翻。而这恰恰是它最有用的时刻。
 *
 * 但**没有落点的就不给点**:一个跳到"大概相关的那一页"的标签比静态的更糟 —— 用户以为
 * 自己会看到那条记录,结果落在一个列表上自己找。
 */

import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/features/media/AssetPreviewModalById", () => ({ AssetPreviewModalById: () => null }));
vi.mock("@/api/client", () => ({ assetThumbnailUrl: () => "" }));

import { ToolResultCard } from "@/components/agent/toolResultShapes";

const HASH = () => window.location.hash;

afterEach(() => {
  window.location.hash = "";
  vi.restoreAllMocks();
});

describe("引用标签", () => {
  it("任务不换页，开任务中心并带上完整 id", () => {
    const events: string[] = [];
    window.addEventListener("mosael:open-tasks", (e) => events.push(String((e as CustomEvent).detail)));
    render(<ToolResultCard value={{ name: "跑一遍", job_id: "c5d80984cd054c86b7405728f6689230" }} />);
    fireEvent.click(screen.getByTitle(/任务 c5d80984cd054c86b7405728f6689230/));
    // 截断只发生在显示上 —— 派发出去的必须是完整 id,否则跟进的是一条不存在的任务。
    expect(events).toEqual(["c5d80984cd054c86b7405728f6689230"]);
    expect(HASH()).toBe("");
  });

  it("工作流跳到工作流页", () => {
    render(<ToolResultCard value={{ name: "改好了", workflow_id: "wf-1" }} />);
    fireEvent.click(screen.getByTitle("工作流 wf-1"));
    expect(HASH()).toBe("#/workflows");
  });

  it("项目带上 id 进剪辑页", () => {
    render(<ToolResultCard value={{ name: "建好了", project_id: "p 1/2" }} />);
    fireEvent.click(screen.getByTitle("项目 p 1/2"));
    // id 要转义 —— 不转的话带空格或斜杠的 id 会把 hash 拆坏。
    expect(HASH()).toBe(`#/editor?p=${encodeURIComponent("p 1/2")}`);
  });

  it("没有落点的仍然是静态的，不伪装成可点", () => {
    render(<ToolResultCard value={{ name: "出图了", generation_id: "g-1", sequence_id: "s-1" }} />);
    for (const label of ["生成 g-1", "序列 s-1"]) {
      const chip = screen.getByTitle(label);
      expect(chip.tagName).toBe("SPAN");
    }
  });
});
