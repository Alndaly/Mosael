/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

/**
 * 3D 场景格自己渲白模参考:选中场景格,面板是同一个壳(BoardComposerShell),底栏两枚芯片 ——「镜头」「渲染内容」,
 * 和工具格的芯片同一个样子;还差什么发送键就是灰的。此前这件事要在场景格旁边另放一格工具格。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.mock("@xyflow/react", () => ({
  NodeToolbar: ({ children }: { children: React.ReactNode }) => children,
  Position: { Bottom: "bottom" },
  NodeResizer: () => null,
  Handle: () => null,
  useStore: () => 1,
}));

import type { BoardItem, BoardProducerInfo, BoardRunRequest } from "@/api/client";
import { withSlotProducer } from "@/api/client";
import { TooltipProvider } from "@/components/ui/tooltip";
import { renderComposer, type ComposerHost } from "@/features/boards/boardComposers";
import { producerOf } from "@/features/boards/boardItemState";
import { SceneNode } from "@/features/boards/boardNodes";
import { NO_UPSTREAM } from "@/features/boards/boardUpstream";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => {},
    releasePointerCapture: () => {},
    scrollIntoView: () => {},
  });
});
const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

//: 形状和 GET /api/boards/producers 发下来的 scene_render 一样(字段是工作流节点那一份,少了场景)。
const RENDER = {
  id: "scene_render",
  type: "scene_render",
  label: "渲白模参考",
  description: "选一个镜头,渲出首尾帧或运镜视频",
  category: "",
  plugin_name: "",
  tool_name: "",
  hosts: ["scene"],
  permission: "edit",
  effects: "none",
  fills_empty_slot: true,
  runs_from_draft: true,
  outputs: [],
  output_types: {},
  output_labels: {},
  body_scope: {},
  config: {
    shot_id: { type: "text", label: "镜头", depends_on: "scene_id", options_from: "scene_shots", sole_option_default: true,
               board_sources: [] },
    render: { type: "string", label: "渲染内容", default: "stills", options: ["stills", "video", "both"],
              option_labels: { stills: "首尾静帧", video: "运镜视频", both: "静帧和运镜视频" }, board_sources: [] },
    project_id: { type: "text", label: "项目", advanced: true, options_from: "projects", board_sources: [] },
  },
} as unknown as BoardProducerInfo;

function stubShots(shots: Record<string, Array<{ value: string; label: string }>>) {
  const asked: string[] = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://x");
    const source = url.searchParams.get("source");
    const parent = url.searchParams.get("parent") ?? "";
    asked.push(`${source}:${parent}`);
    const body = source === "scene_shots" ? (shots[parent] ?? []) : [];
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  }) as never;
  return asked;
}

function mount(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>{node}</TooltipProvider>
    </QueryClientProvider>,
  );
}

const scene = (sceneId: string, extra: Partial<BoardItem> = {}): BoardItem => ({
  id: "s1", kind: "scene", x: 10, y: 20, scene_id: sceneId, text: "客厅", ...extra,
});

/** 走画布挂面板的那一条(renderComposer):存回来的表单照画布那样存,下一次渲染拿到的就是存下的那份。 */
function Stateful({ initial, run, saved }: { initial: BoardItem; run: (request: BoardRunRequest) => Promise<unknown>;
                    saved?: BoardItem["form"][] }) {
  const [item, setItem] = React.useState(initial);
  const producer = producerOf(withSlotProducer(item));
  if (!producer) return null;
  const host: ComposerHost = {
    item,
    position: { x: item.x, y: item.y },
    workspaceId: "w1",
    feeding: NO_UPSTREAM,
    documents: new Map(),
    models: [],
    writing: false,
    setWriting: () => {},
    onFormChange: (form) => {
      saved?.push(form);
      setItem((current) => ({ ...current, form }));
    },
    onPickAsset: () => {},
    run,
    producers: [RENDER],
  };
  return <>{renderComposer(producer, host)}</>;
}

const sendButton = () => document.querySelector<HTMLButtonElement>('[data-board-composer="scene"] [data-board-composer-send]')!;
const chip = (key: string) =>
  within(document.querySelector<HTMLElement>(`[data-board-composer-bar] [data-field-key="${key}"]`)!).getByRole("combobox");

describe("3D 场景格的面板", () => {
  it("新放下的场景格挂渲白模,有缩略图也挂(缩略图不是它的产出)", () => {
    const placed = withSlotProducer(scene("sc", { asset_id: "thumb" }));
    expect(placed.form).toEqual({ producer: "scene_render" });
    expect(producerOf(placed)).toBe("scene_render");
    //: 媒体格有了产出就不再挂面板 —— 那一条不变。
    expect(producerOf({ id: "i", kind: "image", x: 0, y: 0, asset_id: "a", form: { producer: "generate" } })).toBeNull();
  });

  it("正文是场景名和「编辑场景」;底栏两枚芯片写的是值:镜头按这一格的场景列,渲染内容缺省是首尾静帧", async () => {
    const asked = stubShots({ sc: [{ value: "shot-1", label: "开场" }, { value: "shot-2", label: "近景" }] });
    mount(<Stateful initial={scene("sc", { form: { config: { shot_id: "shot-2" } } })} run={async () => undefined} />);

    await waitFor(() => expect(chip("shot_id").textContent).toContain("近景"));
    expect(asked).toContain("scene_shots:sc");
    expect(chip("render").textContent).toContain("首尾静帧");
    const body = document.querySelector<HTMLElement>('[data-board-composer="scene"] [data-board-composer-body]')!;
    expect(body.querySelector("[data-scene-name]")?.textContent).toBe("客厅");
    expect(body.querySelector<HTMLAnchorElement>("[data-scene-open]")?.getAttribute("href")).toBe("#/scenes?scene=sc");
    //: 归档进哪个项目不常用:进「参数」。
    expect(screen.getByRole("button", { name: "boardGenerationSettings" })).toBeTruthy();
    expect(sendButton()).not.toBeDisabled();
  });

  it("换渲染内容存进这一格的表单;点发送跑的就是这一份,落在这一格上", async () => {
    stubShots({ sc: [{ value: "shot-1", label: "开场" }] });
    const run = vi.fn(async (_request: BoardRunRequest) => undefined);
    const saved: BoardItem["form"][] = [];
    mount(<Stateful initial={scene("sc", { form: {} })} run={run} saved={saved} />);

    //: 只有一个镜头:留空就是它,显示成当前值 —— 不替人写进表单(运行时同一条规矩)。
    await waitFor(() => expect(chip("shot_id").textContent).toContain("开场"));
    fireEvent.keyDown(chip("render"), { key: "Enter" });
    fireEvent.click(await screen.findByRole("option", { name: "静帧和运镜视频" }));
    await waitFor(() => expect(saved.at(-1)).toEqual({ config: { render: "both" } }));

    fireEvent.click(sendButton());
    await waitFor(() => expect(run).toHaveBeenCalledTimes(1));
    expect(run.mock.calls[0][0]).toEqual({
      producer: "scene_render", item_id: "s1", kind: "scene", x: 10, y: 20, form: { config: { render: "both" } },
    });
  });

  it("好几个镜头却没挑:发送键是灰的,悬停说还差镜头", async () => {
    stubShots({ sc: [{ value: "shot-1", label: "开场" }, { value: "shot-2", label: "近景" }] });
    mount(<Stateful initial={scene("sc", { form: {} })} run={async () => undefined} />);
    await waitFor(() => expect(sendButton().getAttribute("title")).toContain("boardToolMissing"));
    expect(chip("shot_id").textContent).toBe("镜头");
    expect(sendButton()).toBeDisabled();
  });

  it("场景一个镜头都没有:镜头芯片是灰的,悬停说为什么;发送键也是灰的", async () => {
    stubShots({});
    mount(<Stateful initial={scene("sc", { form: {} })} run={async () => undefined} />);
    await waitFor(() =>
      expect(chip("shot_id").closest("[data-field-key]")?.getAttribute("title")).toContain("boardSceneNoShots"),
    );
    expect(chip("shot_id")).toBeDisabled();
    expect(sendButton()).toBeDisabled();
    expect(sendButton().getAttribute("title")).toContain("boardSceneNoShots");
  });
});

describe("3D 场景格", () => {
  const node = (item: BoardItem) =>
    mount(React.createElement(SceneNode, {
      id: item.id, data: { item, onText: () => {}, onAspect: () => {}, onStop: () => {} }, selected: false,
    } as unknown as React.ComponentProps<typeof SceneNode>));

  it("还没导出缩略图:说这一格能做什么,不是叫人去导出", () => {
    node(scene("sc", { form: { producer: "scene_render" } }));
    expect(document.querySelector("[data-board-scene-hint]")?.textContent).toBe("boardScenePreviewEmpty");
  });

  it("在跑:和别的格子同一个运行外壳(扫光、停止)", () => {
    node(scene("sc", { form: { producer: "scene_render" }, run: { status: "running", job_id: "j1" } }));
    expect(document.querySelector('[data-board-run-status="running"]')).not.toBeNull();
    expect(screen.getByRole("status").getAttribute("aria-busy")).toBe("true");
    expect(document.querySelector("[data-board-stop]")).not.toBeNull();
  });
});
