/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

/**
 * 一格的能力(和空格子上的生成器)的面板:和画板上别的面板同一个壳(BoardComposerShell)。
 *
 *  · 一项能力吃的是它挂着的那一格的内容(`host_fields`)—— 那个字段**不是**芯片、不是正文、不是参数:
 *    正文最上面说「这一下对这一格做什么」(宿主的名字 + 工具那一句说明);
 *  · 上游芯片按后端给的 `board_sources` 过滤(多输入的工具接连进这一格的上游),正文是那段自由的字,
 *    挑一个的字段是底栏芯片(写的是值,没选时写字段名;宽度上限挂在包装那一层),其余进「参数」;
 *  · 还差必填的,发送键是灰的、悬停说差哪几样;有连接时不说「将用你的连接」。
 *
 * 用的工具是假的(`plugin.any.echo`),钉住「面板不认识具体工具」。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.mock("@xyflow/react", () => ({
  NodeToolbar: ({ children }: { children: React.ReactNode }) => children,
  Position: { Bottom: "bottom" },
}));

import type { BoardAbilitySetting, BoardItem, BoardProducerInfo, BoardRunRequest } from "@/api/client";
import { ImagePreviewProvider } from "@/components/app/image-preview";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AbilityComposer } from "@/features/boards/AbilityComposer";
import { renderAbility, renderComposer, slotProducers, type ComposerHost } from "@/features/boards/boardComposers";
import { defaultBindings } from "@/features/boards/boardTools";
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

//: 形状和 GET /api/boards/producers 发下来的一样。一项视频格 / 音频格的能力:素材字段就是宿主。
const TOOL = {
  id: "node:plugin.any.echo",
  type: "plugin.any.echo",
  label: "回声",
  description: "把**文字**原样交回",
  category: "插件",
  plugin_name: "我的回声",
  tool_name: "echo",
  hosts: ["video", "audio"],
  role: "ability",
  host_fields: { video: "clip", audio: "clip" },
  permission: "edit",
  effects: "none",
  fills_empty_slot: false,
  outputs: ["output"],
  output_types: {},
  output_labels: {},
  body_scope: {},
  board_group: "audio",
  board_description: "把这段声音再说一遍。然后放在右边。",
  config: {
    instance_id: { type: "string", options_from: "plugin_instances", advanced: true, label: "连接", board_sources: [] },
    clip: { type: "template", required: true, label: "素材", data_type: "asset", board_sources: ["video", "audio"] },
    text: { type: "template", required: true, label: "文字", description: "要一起念的那句话。多余的话", board_sources: ["note", "document"] },
    picture: { type: "template", label: "图", data_type: "asset", board_sources: ["image", "video", "audio"] },
    mode: { type: "string", options: ["a", "b"], label: "模式", board_sources: [] },
  },
} as unknown as BoardProducerInfo;

const note = (id: string, text: string): BoardItem => ({ id, kind: "note", x: 0, y: 0, text });
const picture: BoardItem = { id: "img", kind: "image", x: 0, y: 0, asset_id: "a1", title: "封面" };
const host = (abilities: Record<string, BoardAbilitySetting> = {}): BoardItem => ({
  id: "v1", kind: "video", x: 400, y: 0, asset_id: "clip-1", title: "开场", form: { abilities, producer: "generate" },
});

function stubApi(connections: Array<{ value: string; label: string }>) {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://x");
    const body = url.pathname.endsWith("/workflows/field-options") ? connections : [];
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  }) as never;
}

function mount(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ImagePreviewProvider>
        <TooltipProvider>{node}</TooltipProvider>
      </ImagePreviewProvider>
    </QueryClientProvider>,
  );
}

/** 面板存回来的设置都照它存 —— 和画布上一样,下一次渲染拿到的就是存下的那份。 */
function Stateful({
  initial = {},
  sources,
  onRun,
  onSaved,
  tool = TOOL,
  hostField = "clip",
}: {
  initial?: BoardAbilitySetting;
  sources: BoardItem[];
  onRun?: (form: unknown) => Promise<unknown>;
  onSaved?: (setting: BoardAbilitySetting) => void;
  tool?: BoardProducerInfo | null;
  hostField?: string | null;
}) {
  const [setting, setSetting] = React.useState<BoardAbilitySetting>(initial);
  return (
    <AbilityComposer
      item={host()}
      tool={tool}
      hostField={hostField}
      setting={setting}
      sources={sources}
      workspaceId="w1"
      busy={false}
      onFormChange={(next) => {
        onSaved?.(next);
        setSetting(next);
      }}
      onRun={onRun ?? (async () => undefined)}
    />
  );
}

const panel = () => document.querySelector<HTMLElement>('[data-board-composer="ability"]')!;
const sendButton = () => document.querySelector<HTMLButtonElement>("[data-board-composer-send]")!;
const chips = (key: string) => document.querySelector<HTMLElement>(`[data-binding-chips="${key}"]`);
const barField = (key: string) =>
  document.querySelector<HTMLElement>(`[data-board-composer-bar] [data-field-key="${key}"]`);

describe("一格的能力的面板", () => {
  it("宿主就是那个输入:素材字段不是芯片、不是正文;正文先说这一下对这一格做什么", async () => {
    stubApi([{ value: "i1", label: "我的回声" }]);
    mount(<Stateful sources={[note("n1", "便签")]} />);
    await waitFor(() => expect(sendButton()).toBeTruthy());
    expect(chips("clip")).toBeNull();
    expect(panel().querySelector('[data-field-key="clip"]')).toBeNull();
    const described = panel().querySelector<HTMLElement>("[data-ability-host]")!;
    expect(described.dataset.abilityHost).toBe("v1");
    //: 宿主的名字 + 工具的名字 + 那一句说明的第一句(给创作者看的,不是节点说明)。
    expect(described.textContent).toContain("开场");
    expect(described.textContent).toContain("回声");
    expect(described.querySelector("[data-ability-what]")?.textContent).toBe("把这段声音再说一遍。");
    //: 发送键说的就是这一项能力(一枚圆键),悬停说结果放在右边。
    expect(sendButton().className).toContain("rounded-full");
    expect(sendButton().getAttribute("aria-label")).toBe("回声");
  });

  it("别的必填输入默认接第一个接得上的上游(不算宿主自己);每个能接上游的字段一组芯片,点一下就存", async () => {
    stubApi([{ value: "i1", label: "我的回声" }]);
    const saved: BoardAbilitySetting[] = [];
    mount(<Stateful sources={[picture, note("n1", "第一张"), note("n2", "第二张")]} onSaved={(one) => saved.push(one)} />);

    await waitFor(() => expect(saved[0]?.bindings).toEqual({ text: [{ from: "n1" }] }));
    const text = () => [...chips("text")!.querySelectorAll<HTMLElement>("[data-binding-source]")];
    expect(text().map((one) => one.dataset.bindingSource)).toEqual(["n1", "n2"]);
    //: 文字字段收一串:再点一张,两张都接上(运行时按连线顺序拼起来)。
    fireEvent.click(text()[1]);
    expect(saved.at(-1)?.bindings).toEqual({ text: [{ from: "n1" }, { from: "n2" }] });
    //: 选填的素材字段不默认接;点图片就接上。宿主那一格不在任何一组里。
    const pictures = [...chips("picture")!.querySelectorAll<HTMLElement>("[data-binding-source]")];
    expect(pictures.map((one) => one.dataset.bindingSource)).toEqual(["img"]);
    fireEvent.click(pictures[0]);
    expect(saved.at(-1)?.bindings).toEqual({ text: [{ from: "n1" }, { from: "n2" }], picture: [{ from: "img" }] });
    expect(chips("mode")).toBeNull();
  });

  it("把最后一枚芯片点掉就是切回手填:正文出现那段字,占位是字段的说明(不是光秃秃的字段名)", async () => {
    stubApi([{ value: "i1", label: "我的回声" }]);
    const saved: BoardAbilitySetting[] = [];
    mount(<Stateful initial={{ bindings: { text: [{ from: "n1" }] } }} sources={[note("n1", "便签")]} onSaved={(one) => saved.push(one)} />);
    fireEvent.click(chips("text")!.querySelector<HTMLElement>('[data-binding-source="n1"]')!);
    await waitFor(() => expect(saved.at(-1)).toMatchObject({ bindings: {}, config: { text: "" } }));
    const body = panel().querySelector<HTMLTextAreaElement>('textarea[data-field-key="text"]')!;
    expect(body.getAttribute("placeholder")).toBe("要一起念的那句话。");
    expect(defaultBindings(TOOL.config as never, { text: "" }, {}, [note("n1", "便签")])).toBeNull();
  });

  it("底栏芯片写的是值,没选时写字段名;宽度上限挂在包装那一层;还差必填时发送键是灰的、悬停说差哪几样", async () => {
    stubApi([{ value: "i1", label: "我的回声" }]);
    const translate = {
      ...TOOL,
      hosts: ["note", "document"],
      host_fields: { note: "text", document: "text" },
      config: {
        text: { type: "text", required: true, label: "文字", board_sources: ["note", "document"] },
        target_lang: { type: "string", required: true, options: ["en", "ja"], option_labels: { en: "英语", ja: "日语" }, label: "目标语言", board_sources: [] },
        engine: { type: "string", options: ["google", "ai"], label: "引擎", board_sources: [] },
        seed: { type: "number", required: true, label: "种子", board_sources: [] },
      },
    } as unknown as BoardProducerInfo;
    mount(<Stateful sources={[]} tool={translate} hostField="text" />);
    await waitFor(() => expect(sendButton()).toBeTruthy());
    //: 宿主(便签的字)不是正文里的一段输入。
    expect(panel().querySelector('textarea[data-field-key="text"]')).toBeNull();
    expect([...document.querySelectorAll<HTMLElement>("[data-board-composer-bar] [data-field-key]")].map((one) => one.dataset.fieldKey))
      .toEqual(["target_lang", "engine"]);
    const lang = barField("target_lang")!;
    expect(within(lang).getByRole("combobox").textContent).toBe("目标语言");
    expect(lang.className).toContain("max-w-[min(15rem,45%)]");
    expect(within(lang).getByRole("combobox").className).not.toContain("max-w-[min(15rem,45%)]");
    expect(sendButton()).toBeDisabled();
    expect(sendButton().getAttribute("title")).toContain("boardToolMissing");
    //: 必填的数字进「参数」,空着 → 按钮上有个点。
    expect(screen.getByRole("button", { name: "boardGenerationSettings" }).dataset.attention).toBe("true");

    fireEvent.keyDown(within(lang).getByRole("combobox"), { key: "Enter" });
    fireEvent.click(await screen.findByRole("option", { name: "英语" }));
    await waitFor(() => expect(within(barField("target_lang")!).getByRole("combobox").textContent).toContain("英语"));
  });

  it("有连接时不说「将用你的连接 X」;没有这个插件的连接:说清楚、给去插件页的入口,不让点运行", async () => {
    stubApi([{ value: "i1", label: "我的回声" }]);
    const { unmount } = mount(<Stateful initial={{ config: { text: "hi" } }} sources={[]} />);
    await waitFor(() => expect(sendButton()).toBeEnabled());
    expect(document.querySelector("[data-tool-connection]")).toBeNull();
    unmount();

    stubApi([]);
    mount(<Stateful initial={{ config: { text: "hi" } }} sources={[]} />);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("boardToolNoConnection".replace("{plugin}", "我的回声"));
    expect(within(alert).getByRole("link", { name: "boardToolOpenPlugins" }).getAttribute("href")).toBe("#/plugins");
    expect(sendButton().disabled).toBe(true);
  });

  it("清单里没有这一项(插件卸了、这个人没接):不给表单", () => {
    stubApi([]);
    mount(<Stateful sources={[]} tool={null} />);
    expect(screen.getByRole("alert").textContent).toContain("boardToolUnavailable");
    expect(document.querySelector("[data-board-composer-send]")).toBeNull();
  });
});

describe("能力的运行、空格子上的生成器", () => {
  const base = (item: BoardItem, run: ComposerHost["run"]): ComposerHost => ({
    item,
    position: { x: 420, y: 10 },
    workspaceId: "w1",
    feeding: NO_UPSTREAM,
    documents: new Map(),
    models: [],
    writing: false,
    setWriting: () => undefined,
    onFormChange: () => undefined,
    onPickAsset: () => undefined,
    run,
    producers: [TOOL],
  });

  it("跑一项能力:发出去的是这一项、宿主那一格和它存着的设置;存设置走 onSave(宿主自己的表单不动)", async () => {
    stubApi([{ value: "i1", label: "我的回声" }]);
    const run = vi.fn(async (_request: BoardRunRequest) => undefined);
    const onSave = vi.fn();
    const item = host({ [TOOL.id]: { config: { mode: "b", text: "hi" } } });
    const { onFormChange: _unused, ...rest } = base(item, run);
    mount(<>{renderAbility(TOOL.id as never, { ...rest, onSave })}</>);
    await waitFor(() => expect(sendButton()).toBeEnabled());
    fireEvent.click(sendButton());
    await waitFor(() => expect(run).toHaveBeenCalledTimes(1));
    expect(run.mock.calls[0][0]).toEqual({
      producer: TOOL.id,
      item_id: "v1",
      kind: "video",
      x: 420,
      y: 10,
      form: { config: { mode: "b", text: "hi" }, bindings: {} },
    });
  });

  it("空格子上的生成器:面板是它自己的表单(没有宿主那一行),正文是那段提示词,发送键写「运行」", async () => {
    stubApi([{ value: "i1", label: "我的回声" }]);
    const generator = {
      ...TOOL,
      id: "node:plugin.any.paint",
      type: "plugin.any.paint",
      role: "slot",
      hosts: ["image"],
      host_fields: {},
      fills_empty_slot: true,
      config: { prompt: { type: "template", label: "提示词", board_sources: ["note", "document"] } },
    } as unknown as BoardProducerInfo;
    const run = vi.fn(async (_request: BoardRunRequest) => undefined);
    const slot: BoardItem = { id: "i1", kind: "image", x: 0, y: 0, form: { config: { prompt: "一只猫" }, bindings: {} } };
    mount(<>{renderComposer(generator.id as never, { ...base(slot, run), producers: [generator] })}</>);
    await waitFor(() => expect(sendButton()).toBeEnabled());
    expect(document.querySelector('[data-board-composer="generator"]')).not.toBeNull();
    expect(document.querySelector("[data-ability-host]")).toBeNull();
    expect(document.querySelector<HTMLTextAreaElement>('textarea[data-field-key="prompt"]')?.value).toBe("一只猫");
    expect(sendButton().getAttribute("aria-label")).toBe("boardToolRun");
    fireEvent.click(sendButton());
    await waitFor(() => expect(run).toHaveBeenCalledTimes(1));
    expect(run.mock.calls[0][0]).toMatchObject({ producer: generator.id, item_id: "i1", kind: "image",
      form: { config: { prompt: "一只猫" }, bindings: {} } });
  });

  it("空槽的产出者切换:内置的和插件的生成器一起列(能填空槽、挂得在这种格子上的);有产出了不给", () => {
    const producer = (id: string, hosts: string[], fills = true) =>
      ({ ...TOOL, id, type: id, hosts, role: "slot", fills_empty_slot: fills }) as unknown as BoardProducerInfo;
    const registry = [
      producer("speak", ["audio"]),
      producer("generate", ["image", "video"]),
      producer("trim", ["video", "audio"], false),
      producer("node:plugin.any.music", ["audio"]),
    ];
    const empty: BoardItem = { id: "s", kind: "audio", x: 0, y: 0, form: { producer: "speak" } };
    expect(slotProducers(empty, registry).map((one) => one.id)).toEqual(["speak", "node:plugin.any.music"]);
    //: 选着插件生成器的那一格照样能切回去。
    expect(slotProducers({ ...empty, form: { producer: "node:plugin.any.music" } }, registry)).toHaveLength(2);
    expect(slotProducers({ ...empty, kind: "image", form: { producer: "generate" } }, registry)).toEqual([]);
    expect(slotProducers({ ...empty, asset_id: "done" }, registry)).toEqual([]);
    expect(slotProducers(empty, undefined)).toEqual([]);
  });
});
