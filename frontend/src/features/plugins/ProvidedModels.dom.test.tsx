/** @vitest-environment jsdom */

/**
 * 替宿主做生成的插件在插件页上那一行**摘要**:几个、什么时候刷的、刷不出来的原因(只说第一句人话)。
 * 逐张看、按名字找是工具栏那颗「模型库 / 工作流库」的完整窗口 —— 这里不再另开一个重复的「查看」入口(已去掉)。
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) =>
    ({
      pluginGenerationError: "pluginGenerationError {error}",
      pluginGenerationStale: "没刷出来:{error} · 列着的是 {time}的清单",
      pluginGenerationNever: "pluginGenerationNever",
      pluginGenerationCount: "pluginGenerationCount",
      pluginGenerationModels: "可生成的{noun}",
      pluginGenerationModelsDesc: "说明 {noun}",
    })[key] ?? key,
  usePreferences: () => ({ locale: "zh" }),
}));

import type { PluginInstance } from "@/api/client";
import { GenerationModelsRow } from "./ProvidedModels";

const instance = { id: "i1", name: "ComfyUI · 本机" } as PluginInstance;

describe("可生成的{noun}那一行摘要", () => {
  it("说几个、什么时候刷的;不另开「查看」入口(和工具栏的模型库/工作流库重复,已去掉)", () => {
    render(
      <GenerationModelsRow
        instance={instance}
        noun="工作流"
        status={{ models: 40, refreshed_at: "2026-09-25T10:00:00+00:00", error: "" }}
      />,
    );
    expect(screen.getByText("pluginGenerationCount")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /pluginModelsView|查看/ })).toBeNull();
  });

  it("没刷出来:说原因(红色、有宽度上限、只摆第一句人话,原文悬停看)", () => {
    render(
      <GenerationModelsRow
        instance={instance}
        noun="工作流"
        status={{ models: null, error: "连不上这台 ComfyUI,确认它在运行、地址填对\nhttp://127.0.0.1:8188:[Errno 61] Connection refused" }}
      />,
    );
    const text = screen.getByText("pluginGenerationError 连不上这台 ComfyUI,确认它在运行、地址填对");
    expect(text.className).toContain("text-destructive");
    expect(text.className).toMatch(/max-w-/);
    expect(document.body.textContent).not.toContain("Errno");
  });

  it("刷不出来、手里是上一次的数:说清列着的是什么时候的清单", () => {
    render(
      <GenerationModelsRow
        instance={instance}
        noun="工作流"
        status={{ models: 40, refreshed_at: "2026-09-25T10:00:00+00:00", error: "连不上这台 ComfyUI" }}
      />,
    );
    expect(document.body.textContent).toMatch(/没刷出来:连不上这台 ComfyUI · 列着的是 .+的清单/);
  });

  it("从没刷出来过:照实说,不假装有", () => {
    render(<GenerationModelsRow instance={instance} noun="工作流" status={{ models: null, error: "" }} />);
    expect(screen.getByText("pluginGenerationNever")).toBeTruthy();
  });
});
