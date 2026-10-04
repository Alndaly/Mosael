/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";

/**
 * 画板上**一张 ComfyUI 工作流只有一个入口**。用户报的:「古风女孩.json · ComfyUI」在图片格的模型下拉里,
 * 「工作流 · 古风女孩」又在格子顶上的「…」里 —— 两条路参数和行为不同。插件 1.6.0 起能当生成模型用的每张工作流的工具
 * 都说「我和那个模型是同一件事」(`mirrors`),后端的产出者清单(GET /api/boards/producers)里就不再有它;「…」和空格子的
 * 切换都只读这份清单,不另从插件的工具表里加。不是生成模型的工作流(只交出一段字的打标签)照旧是格子的一项能力。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN", t: (key: string) => key }),
}));

import type { BoardCanvas as Canvas, BoardItem, BoardProducerInfo, GenerationOption } from "@/api/client";
import { ImagePreviewProvider } from "@/components/app/image-preview";
import { BoardCanvas } from "@/features/boards/BoardCanvas";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  Object.assign(Element.prototype, { scrollIntoView: () => {}, hasPointerCapture: () => false, releasePointerCapture: () => {} });
});
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  globalThis.fetch = vi.fn(async () => new Response("[]", { status: 200, headers: { "content-type": "application/json" } })) as never;
});
afterEach(() => {
  vi.useRealTimers();
});

const producer = (id: string, label: string, extra: Partial<BoardProducerInfo> = {}): BoardProducerInfo =>
  ({
    id, type: id.replace(/^node:/, ""), label, description: "", category: "", config: {}, outputs: [], output_types: {},
    output_labels: {}, plugin_name: "", tool_name: "", body_scope: {}, hosts: [], role: "slot", host_fields: {},
    permission: "edit", effects: "none", fills_empty_slot: false, board_group: "", board_group_label: "",
    board_description: `${label}的一句话`, ...extra,
  }) as BoardProducerInfo;
const ability = (id: string, label: string, hosts: string[]) =>
  producer(id, label, {
    hosts, role: "ability", host_fields: Object.fromEntries(hosts.map((kind) => [kind, "image_1"])), plugin_name: "ComfyUI",
    config: { image_1: { type: "template", required: true, label: "图", board_sources: hosts } },
  });

//: 一位接了 ComfyUI 的用户拿到的清单:「古风女孩」那张的工具说了 mirrors,后端不发;打标签那张不是生成模型,照发。
const PRODUCERS = [
  producer("generate", "生成", { hosts: ["image", "video"], fills_empty_slot: true }),
  ability("node:plugin.x.a", "抠图", ["image"]),
  ability("node:plugin.x.b", "修脸", ["image"]),
  ability("node:plugin.x.c", "扩图", ["image"]),
  ability("node:plugin.x.d", "去水印", ["image"]),
  //: 直接摆 4 项,第 5 项起收进「…」。
  ability("node:plugin.dev.mosael.comfyui.wf_tagger", "工作流 · tagger", ["image"]),
];

const GIRL: GenerationOption = {
  id: "girl", provider_profile_id: "comfy", plugin_instance_id: "", profile_name: "ComfyUI", label: "古风女孩.json · ComfyUI",
  adapter_available: true, is_default: true, capabilities_known: true, provider: "plugin:dev.mosael.comfyui",
  model: "古风女孩.json", kind: "image", capabilities: { prompt: "optional", parameter_keys: [] },
} as GenerationOption;

function mount(items: BoardItem[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const canvas: Canvas = { items, edges: [], markers: [] };
  render(
    <QueryClientProvider client={client}>
      <ImagePreviewProvider>
        <div style={{ width: 800, height: 600 }}>
          <BoardCanvas
            boardId="b1" workspaceId="w1" canvas={canvas} onChange={() => undefined} onPickAsset={() => undefined}
            onRun={vi.fn(async () => undefined)} producers={PRODUCERS} models={[GIRL]}
          />
        </div>
      </ImagePreviewProvider>
    </QueryClientProvider>,
  );
}

const select = (id: string) =>
  act(() => {
    document.querySelector(`[data-id="${id}"]`)!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });

it("工作流在图片格的模型下拉里,「…」里不再有同一张工作流;不是生成模型的那张照旧在「…」里", () => {
  mount([
    { id: "pic", kind: "image", x: 0, y: 0, width: 260, height: 180, asset_id: "a1" },
    { id: "slot", kind: "image", x: 400, y: 0, width: 260, height: 180, form: { producer: "generate" } },
  ]);
  select("pic");
  act(() => document.querySelector<HTMLButtonElement>('[data-board-abilities] button[aria-label="boardMoreAbilities"]')!.click());
  const more = screen.getByRole("menu", { name: "boardMoreAbilities" });
  const rows = [...more.querySelectorAll('[role="menuitem"]')].map((one) => one.textContent ?? "");
  expect(rows.some((one) => one.includes("工作流 · tagger"))).toBe(true);
  expect(rows.some((one) => one.includes("古风女孩"))).toBe(false);
  fireEvent.keyDown(more, { key: "Escape" });

  select("slot");
  const picker = screen.getAllByRole("combobox").find((one) => one.textContent?.includes("古风女孩.json"));
  expect(picker, "模型下拉里就是这张工作流").toBeDefined();
});
