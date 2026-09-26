/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 能力住在内容格上(ADR 0025 修订):选中一格,它上方的操作条列出这一格会的事 —— 一排图标(TapNow 那样),
 * 内置的在前、至多直接摆 4 项,其余收进「⋯」;点一项,它的面板挂在格子下面,点另一项下面那块就换成它的,
 * 再点一次收起。挂在哪由后端说(`role` + `hosts`),前端不另写一张「什么格子会什么」的表。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN", t: (key: string) => key }),
}));

import type { BoardCanvas as Canvas, BoardItem, BoardProducerInfo } from "@/api/client";
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

//: 形状和 GET /api/boards/producers 发下来的一样(注册表的顺序:内置的、内置节点、插件工具)。
const producer = (id: string, label: string, extra: Partial<BoardProducerInfo> = {}): BoardProducerInfo =>
  ({
    id, type: id.replace(/^node:/, ""), label, description: "", category: "", config: {}, outputs: [], output_types: {},
    output_labels: {}, plugin_name: "", tool_name: "", body_scope: {}, hosts: [], role: "slot", host_fields: {},
    permission: "edit", effects: "none", fills_empty_slot: false, board_group: "", board_group_label: "",
    board_description: `${label}的一句话`, ...extra,
  }) as BoardProducerInfo;
const ability = (id: string, label: string, hosts: string[], field = "asset_id", extra: Partial<BoardProducerInfo> = {}) =>
  producer(id, label, {
    hosts, role: "ability", host_fields: Object.fromEntries(hosts.map((kind) => [kind, field])),
    config: { [field]: { type: "template", required: true, label: field, board_sources: hosts } }, ...extra,
  });

const PRODUCERS = [
  producer("generate", "生成", { hosts: ["image", "video"], fills_empty_slot: true }),
  producer("write", "写字", { hosts: ["note"], fills_empty_slot: true }),
  producer("speak", "配音", { hosts: ["audio"], fills_empty_slot: true }),
  producer("trim", "截一段", { hosts: ["video", "audio"] }),
  ability("node:transcribe_asset", "素材转写", ["video", "audio"]),
  ability("node:video_to_gif", "视频转 GIF", ["video"]),
  ability("node:translate", "翻译", ["note", "document"], "text", {
    config: {
      text: { type: "template", required: true, label: "文字", board_sources: ["note", "document"] },
      target_lang: { type: "string", required: true, options: ["en", "ja"], label: "目标语言", board_sources: [] },
    },
  }),
  ability("node:separate_audio", "分离人声与背景音", ["video", "audio"]),
  ability("node:denoise_audio", "降噪", ["video", "audio"]),
  ability("node:plugin.x.upscale", "放大", ["video"], "clip", { plugin_name: "放大器" }),
  //: 插件的生成器:空的音频格可以挑它(和配音一起在切换里)。
  producer("node:plugin.x.music", "配乐", { hosts: ["audio"], fills_empty_slot: true }),
];

function mount(items: BoardItem[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const canvas: Canvas = { items, edges: [], markers: [] };
  render(
    <QueryClientProvider client={client}>
      <ImagePreviewProvider>
        <div style={{ width: 800, height: 600 }}>
          <BoardCanvas
            boardId="b1"
            workspaceId="w1"
            canvas={canvas}
            onChange={() => undefined}
            onPickAsset={() => undefined}
            onRun={vi.fn(async () => undefined)}
            producers={PRODUCERS}
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
/** 操作条上能力那一段的每一枚:内置动作按 `data-board-action`、能力按 `data-board-ability`,名字在 aria-label。 */
const bar = () =>
  [...document.querySelectorAll<HTMLButtonElement>("[data-board-abilities] button")].map(
    (one) => one.getAttribute("aria-label") ?? "",
  );
const abilityButton = (label: string) =>
  document.querySelector<HTMLButtonElement>(`[data-board-abilities] button[aria-label="${label}"]`)!;
const composer = () => document.querySelector<HTMLElement>("[data-board-composer]");

const audio: BoardItem = { id: "au", kind: "audio", x: 0, y: 0, width: 280, height: 72, asset_id: "a1", title: "旁白" };
const video: BoardItem = { id: "vi", kind: "video", x: 0, y: 0, width: 320, height: 200, asset_id: "v1" };
const noteItem: BoardItem = { id: "n1", kind: "note", x: 0, y: 0, width: 220, height: 140, text: "你好", form: { producer: "write" } };

describe("操作条上的能力", () => {
  it("音频格:剪一段、换一份,接着是它的能力 —— 转写、分离、降噪;每一枚都是图标,名字在悬停和读屏里", () => {
    mount([audio]);
    select("au");
    expect(bar()).toEqual(["boardTrim", "boardReplaceAsset", "素材转写", "分离人声与背景音", "降噪"]);
    const transcribe = abilityButton("素材转写");
    expect(transcribe.dataset.boardAbility).toBe("node:transcribe_asset");
    expect(transcribe.textContent).toBe("");
    expect(transcribe.querySelector("svg")).not.toBeNull();
    //: 悬停(键盘聚焦同一条路)马上出说明:名字一行、那一句说明一行 —— 不是要停一秒多的原生 title。
    expect(transcribe.title).toBe("");
    act(() => transcribe.focus());
    expect(screen.getByRole("tooltip").textContent).toBe("素材转写素材转写的一句话");
    //: 转 GIF 是视频格的,不在音频格上;翻译是便签的。
    expect(bar()).not.toContain("视频转 GIF");
    expect(bar()).not.toContain("翻译");
  });

  it("便签:让 AI 写和翻译;视频格:内置的四项直接摆,插件的那一项收进「⋯」", () => {
    mount([noteItem, video]);
    select("n1");
    expect(bar()).toEqual(["boardAskAiWrite", "翻译"]);
    select("vi");
    expect(bar()).toEqual([
      "boardPreview", "boardTrim", "boardReplaceAsset", "素材转写", "视频转 GIF", "分离人声与背景音", "降噪", "boardMoreAbilities",
    ]);
    act(() => abilityButton("boardMoreAbilities").click());
    const more = screen.getByRole("menu", { name: "boardMoreAbilities" });
    const row = [...more.querySelectorAll<HTMLElement>('[role="menuitem"]')].find((one) => one.textContent?.includes("放大"))!;
    expect(row.querySelector("svg"), "「⋯」里每一行都有图标").not.toBeNull();
    //: 从「⋯」里点开的那一项摆到外面来(按下态看得见是谁的面板)。
    act(() => row.click());
    expect(abilityButton("放大").getAttribute("aria-pressed")).toBe("true");
    expect(composer()?.dataset.boardComposer).toBe("ability");
  });

  it("点一项,它的面板挂在格子下面;点另一项,下面那块换成它的;再点一次收起", () => {
    mount([audio]);
    select("au");
    expect(composer()).toBeNull();
    act(() => abilityButton("素材转写").click());
    expect(composer()?.dataset.boardComposer).toBe("ability");
    expect(document.querySelector("[data-board-composer-send]")?.getAttribute("aria-label")).toBe("素材转写");
    expect(abilityButton("素材转写").getAttribute("aria-pressed")).toBe("true");

    act(() => abilityButton("降噪").click());
    expect(document.querySelectorAll("[data-board-composer]")).toHaveLength(1);
    expect(document.querySelector("[data-board-composer-send]")?.getAttribute("aria-label")).toBe("降噪");
    expect(abilityButton("素材转写").getAttribute("aria-pressed")).toBe("false");

    //: 剪一段也是下面那一块:换成截取面板,能力的那块收起。
    act(() => abilityButton("boardTrim").click());
    expect(composer()?.dataset.boardComposer).toBe("trim");
    act(() => abilityButton("降噪").click());
    expect(composer()?.dataset.boardComposer).toBe("ability");

    act(() => abilityButton("降噪").click());
    expect(composer()).toBeNull();
  });

  it("便签上点开翻译:写字的面板不挂;宿主的字就是输入 —— 面板上没有要填的原文,只差目标语言", () => {
    mount([noteItem]);
    select("n1");
    act(() => abilityButton("翻译").click());
    expect(document.querySelector('[data-board-composer="write"]')).toBeNull();
    expect(document.querySelector("[data-ability-host]")?.getAttribute("data-ability-host")).toBe("n1");
    expect(document.querySelector('textarea[data-field-key="text"]')).toBeNull();
    const send = document.querySelector<HTMLButtonElement>("[data-board-composer-send]")!;
    expect(send.disabled).toBe(true);
    expect(send.title).toContain("boardToolMissing");
    //: 换到让 AI 写:下面那块换成写字的。
    act(() => abilityButton("boardAskAiWrite").click());
    expect(composer()?.dataset.boardComposer).toBe("write");
    expect(document.querySelector("[data-ability-host]")).toBeNull();
  });

  it("还没有内容的格子没有能力可点(空的音频槽只有产出方式的切换,插件的生成器也在里面)", () => {
    mount([{ id: "slot", kind: "audio", x: 0, y: 0, width: 280, height: 72, form: { producer: "speak" } }]);
    select("slot");
    expect(bar()).toEqual(["boardReplaceAsset"]);
    const radios = [...document.querySelectorAll('[role="radiogroup"] [role="radio"]')].map((one) => one.textContent);
    expect(radios).toEqual(["配音", "配乐"]);
    act(() => (document.querySelectorAll<HTMLButtonElement>('[role="radiogroup"] [role="radio"]')[1]).click());
    expect(composer()?.dataset.boardComposer).toBe("generator");
  });

  it("Esc 收起点开的那一块", () => {
    mount([audio]);
    select("au");
    act(() => abilityButton("素材转写").click());
    expect(composer()).not.toBeNull();
    act(() => {
      fireEvent.keyDown(window, { key: "Escape" });
    });
    expect(composer()).toBeNull();
  });
});

describe("一项能力在跑:格子自己的内容照常画,底边挂一条运行态", () => {
  it("在跑:写着哪一项、能停;跑挂了:不套红框,原因只在选中时挂出来", () => {
    const onStop = vi.fn();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const running: BoardItem = { ...audio, run: { status: "running", job_id: "job-1", ability: "node:transcribe_asset" } };
    const failed: BoardItem = { ...video, run: { status: "failed", error: "没有声音", ability: "node:video_to_gif" } };
    render(
      <QueryClientProvider client={client}>
        <ImagePreviewProvider>
          <BoardCanvas boardId="b1" workspaceId="w1" canvas={{ items: [running, failed], edges: [], markers: [] }}
                       onChange={() => undefined} onPickAsset={() => undefined} producers={PRODUCERS} onStop={onStop} />
        </ImagePreviewProvider>
      </QueryClientProvider>,
    );
    const strip = document.querySelector<HTMLElement>('[data-id="au"] [data-board-ability-run]')!;
    expect(strip.dataset.boardAbilityRun).toBe("running");
    expect(strip.textContent).toContain("素材转写");
    //: 音频本身还在(那段音频是这一项的输入,不是一块占位)。
    expect(document.querySelector('[data-id="au"] [data-board-empty-slot]')).toBeNull();
    act(() => strip.querySelector<HTMLButtonElement>("[data-board-stop]")!.click());
    expect(onStop).toHaveBeenCalledWith("au");

    const card = document.querySelector<HTMLElement>('[data-id="vi"] [data-board-run-status]')!;
    expect(card.dataset.boardRunStatus).toBe("failed");
    expect(card.className).not.toContain("border-destructive");
    expect(document.querySelector('[data-id="vi"] [data-board-ability-run]')).toBeNull();
    select("vi");
    expect(document.querySelector('[data-id="vi"] [data-board-ability-run]')?.textContent).toContain("没有声音");
  });
});

describe("画板上造不出工具格", () => {
  it("格子只有七种;拉线菜单、「添加」里都没有工具(见 BoardPendingLink / boardAddCatalog 的测试)", async () => {
    const { BOARD_NODE_TYPES, DEFAULT_SIZE } = await import("@/features/boards/boardNodes");
    const kinds = ["note", "image", "video", "audio", "frame", "scene", "document"];
    expect(Object.keys(BOARD_NODE_TYPES).sort()).toEqual([...kinds].sort());
    expect(Object.keys(DEFAULT_SIZE).sort()).toEqual([...kinds].sort());
  });
});
