/** @vitest-environment jsdom */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { needsRunParams, RunParamsDialog } from "@/features/workflows/RunParamsDialog";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

/** 开始节点:`topic` 必填没默认值,`tone` 必填有默认值,`count` 选填。 */
const GRAPH = {
  nodes: [
    {
      id: "start",
      type: "start",
      config: { params: { topic: "", tone: "克制", count: 4 }, required_params: ["topic", "tone"] },
    },
  ],
  edges: [],
};

describe("运行前问参数(画布上写的「运行时填」)", () => {
  it("有必填又没有默认值的参数才问;都有默认值、或没有开始节点就不问", () => {
    expect(needsRunParams(GRAPH)).toBe(true);
    const filled = { ...GRAPH, nodes: [{ ...GRAPH.nodes[0], config: { ...GRAPH.nodes[0].config, params: { topic: "雨夜", tone: "", count: 4 }, required_params: ["topic"] } }] };
    expect(needsRunParams(filled)).toBe(false);
    expect(needsRunParams({ nodes: [], edges: [] })).toBe(false);
  });

  it("没填必填的那一项点运行:不发,那一行说缺什么;填好了只带填了的那几项(数字照数字存)", () => {
    const onRun = vi.fn();
    render(<RunParamsDialog graph={GRAPH} open onOpenChange={() => undefined} onRun={onRun} running={false} />);
    fireEvent.click(screen.getByRole("button", { name: "wfRun" }));
    expect(onRun).not.toHaveBeenCalled();
    expect(screen.getByText("taskParamMissing")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("topic *"), { target: { value: "深夜便利店" } });
    fireEvent.change(screen.getByLabelText("count"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "wfRun" }));
    expect(onRun).toHaveBeenCalledWith({ topic: "深夜便利店", count: 2 });
  });
});
