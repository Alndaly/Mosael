/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

/**
 * 工具格的面板:和画板上别的面板同一个壳(BoardComposerShell)。上游芯片按后端给的 `board_sources` 过滤,
 * 正文是那段自由的字,挑一个的字段是底栏芯片(必填在前、至多三枚),其余进「参数」;分到哪一块全按字段
 * 声明推。再加画板自己的一件事:「用谁的连接」。
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

import type { BoardItem, BoardProducerInfo, BoardRunRequest } from "@/api/client";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ActionComposer } from "@/features/boards/ActionComposer";
import { defaultBindings } from "@/features/boards/boardTools";
import { renderComposer, slotProducers, type ComposerHost } from "@/features/boards/boardComposers";
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

//: 形状和 GET /api/boards/producers 发下来的一样。
const TOOL = {
  id: "node:plugin.any.echo",
  type: "plugin.any.echo",
  label: "回声",
  description: "把**文字**原样交回",
  category: "插件",
  plugin_name: "我的回声",
  tool_name: "echo",
  hosts: ["action"],
  permission: "edit",
  effects: "none",
  fills_empty_slot: false,
  outputs: ["output"],
  output_types: {},
  output_labels: {},
  body_scope: {},
  config: {
    instance_id: { type: "string", options_from: "plugin_instances", advanced: true, label: "连接", board_sources: [] },
    text: { type: "template", required: true, label: "文字", board_sources: ["note", "document"] },
    picture: { type: "template", label: "图", data_type: "asset", board_sources: ["image", "video", "audio"] },
    mode: { type: "string", options: ["a", "b"], label: "模式", board_sources: [] },
  },
} as unknown as BoardProducerInfo;

const note = (id: string, text: string): BoardItem => ({ id, kind: "note", x: 0, y: 0, text });
const picture: BoardItem = { id: "img", kind: "image", x: 0, y: 0, asset_id: "a1", title: "封面" };
const action = (form: BoardItem["form"] = {}): BoardItem => ({ id: "a1", kind: "action", x: 400, y: 0, form });

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
      <TooltipProvider>{node}</TooltipProvider>
    </QueryClientProvider>,
  );
}

/** 面板存回来的表单都照它存 —— 和画布上一样,下一次渲染拿到的就是存下的那份。 */
function Stateful({
  initial,
  sources,
  onRun,
  onSaved,
  tool = TOOL,
}: {
  initial: BoardItem;
  sources: BoardItem[];
  onRun?: (form: unknown) => Promise<unknown>;
  onSaved?: (form: BoardItem["form"]) => void;
  tool?: BoardProducerInfo | null;
}) {
  const [item, setItem] = React.useState(initial);
  return (
    <ActionComposer
      item={item}
      tool={tool}
      sources={sources}
      workspaceId="w1"
      busy={false}
      onFormChange={(form) => {
        onSaved?.(form);
        setItem((current) => ({ ...current, form }));
      }}
      onRun={onRun ?? (async () => undefined)}
    />
  );
}

const panel = () => document.querySelector<HTMLElement>('[data-board-composer="tool"]')!;
const sendButton = () => document.querySelector<HTMLButtonElement>("[data-board-composer-send]")!;
const chips = (key: string) => document.querySelector<HTMLElement>(`[data-binding-chips="${key}"]`);
const barField = (key: string) =>
  document.querySelector<HTMLElement>(`[data-board-composer-bar] [data-field-key="${key}"]`);

describe("工具格的面板", () => {
  it("和别的面板同一个壳:上面是上游芯片,正文是那段字,底栏是设置芯片 +「参数」+ 圆形发送键 —— 不是一列带大标签的表单", async () => {
    stubApi([{ value: "i1", label: "我的回声" }]);
    mount(<Stateful initial={action()} sources={[]} />);
    await waitFor(() => expect(sendButton()).toBeTruthy());
    //: 正文就是那段要交给工具的字(第一个没接上游的文字字段),不是一行「文字 *」标签 + 输入框。
    const body = panel().querySelector<HTMLElement>("[data-board-composer-body]")!;
    expect(body.querySelector('textarea[data-field-key="text"]')?.getAttribute("placeholder")).toBe("文字");
    //: 挑一个的字段是底栏里的一枚芯片(标签在芯片里)。
    expect(within(barField("mode")!).getByRole("combobox").textContent).toContain("模式");
    //: 其余的进「参数」;发送键是那枚圆键,和生成面板一样。
    expect(screen.getByRole("button", { name: "boardGenerationSettings" })).toBeTruthy();
    expect(sendButton().className).toContain("rounded-full");
    expect(sendButton().getAttribute("aria-label")).toBe("boardToolRun");
    //: 没有检查器那一列的大标签和「手填 / 接上游」切换。
    expect(document.querySelector("[data-field-key] > span > em")).toBeNull();
    expect(screen.queryByText("wfInputManual")).toBeNull();
  });

  it("必填的文字字段默认接上第一张便签;每个能接上游的字段一组芯片,只列接得上的上游,点一下就存", async () => {
    stubApi([{ value: "i1", label: "我的回声" }]);
    const saved: BoardItem["form"][] = [];
    mount(<Stateful initial={action()} sources={[picture, note("n1", "第一张"), note("n2", "第二张")]} onSaved={(form) => saved.push(form)} />);

    await waitFor(() => expect(saved[0]?.bindings).toEqual({ text: [{ from: "n1" }] }));
    const text = () => [...chips("text")!.querySelectorAll<HTMLElement>("[data-binding-source]")];
    //: 文字字段只接便签和文档 —— 图片不在这一组里。
    expect(text().map((one) => one.dataset.bindingSource)).toEqual(["n1", "n2"]);
    expect(text()[0].getAttribute("aria-pressed")).toBe("true");
    //: 接上了:正文里不再摆那个字段的输入框。
    expect(panel().querySelector('textarea[data-field-key="text"]')).toBeNull();

    //: 文字字段收一串:再点一张,两张都接上(运行时按连线顺序拼起来)。
    fireEvent.click(text()[1]);
    expect(saved.at(-1)?.bindings).toEqual({ text: [{ from: "n1" }, { from: "n2" }] });

    //: 素材字段不是必填,不默认接;它那一组里点图片就接上。
    const pictures = [...chips("picture")!.querySelectorAll<HTMLElement>("[data-binding-source]")];
    expect(pictures.map((one) => one.dataset.bindingSource)).toEqual(["img"]);
    expect(pictures[0].getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(pictures[0]);
    expect(saved.at(-1)?.bindings).toEqual({ text: [{ from: "n1" }, { from: "n2" }], picture: [{ from: "img" }] });
    //: 固定选项的字段没有上游芯片 —— 它在底栏。
    expect(chips("mode")).toBeNull();
  });

  it("把最后一枚芯片点掉就是切回手填:正文出现那段字,不会又被默认绑回去", async () => {
    stubApi([{ value: "i1", label: "我的回声" }]);
    const saved: BoardItem["form"][] = [];
    mount(<Stateful initial={action({ bindings: { text: [{ from: "n1" }] } })} sources={[note("n1", "便签")]} onSaved={(form) => saved.push(form)} />);
    fireEvent.click(chips("text")!.querySelector<HTMLElement>('[data-binding-source="n1"]')!);
    await waitFor(() => expect(saved.at(-1)).toMatchObject({ bindings: {}, config: { text: "" } }));
    expect(panel().querySelector('textarea[data-field-key="text"]')).not.toBeNull();
    expect(defaultBindings(TOOL.config as never, { text: "" }, {}, [note("n1", "便签")])).toBeNull();
  });

  it("底栏的芯片:挑一个的字段,必填的排前面,至多三枚;其余进「参数」,里面有必填还空着时按钮上一个点", async () => {
    stubApi([{ value: "i1", label: "我的回声" }]);
    const many = {
      ...TOOL,
      config: {
        ...TOOL.config,
        style: { type: "string", options: ["x", "y"], label: "风格", board_sources: [] },
        speed: { type: "string", options: ["slow", "fast"], label: "速度", board_sources: [] },
        lang: { type: "string", required: true, options: ["en", "ja"], option_labels: { en: "英语", ja: "日语" }, label: "目标语言", board_sources: [] },
        seed: { type: "number", required: true, label: "种子", board_sources: [] },
      },
    } as unknown as BoardProducerInfo;
    mount(<Stateful initial={action()} sources={[]} tool={many} />);
    await waitFor(() => expect(sendButton()).toBeTruthy());
    const bar = [...document.querySelectorAll<HTMLElement>("[data-board-composer-bar] [data-field-key]")].map((one) => one.dataset.fieldKey);
    expect(bar).toEqual(["lang", "mode", "style"]);
    //: 必填还没选:芯片上写「待选」。
    expect(within(barField("lang")!).getByRole("combobox").textContent).toContain("boardToolUnset");
    //: 第四个挑一个的字段(速度)和必填的数字(种子)进「参数」;种子空着 → 按钮上有个点。
    const settings = screen.getByRole("button", { name: "boardGenerationSettings" });
    expect(settings.dataset.attention).toBe("true");
    fireEvent.click(settings);
    const popover = await screen.findByRole("dialog");
    expect(popover.querySelector('[data-field-key="speed"]')).not.toBeNull();
    expect(popover.querySelector('[data-field-key="seed"]')).not.toBeNull();
    //: 紧凑的一行一项(和生成面板的参数弹层一个样子),不是检查器那一列。
    expect(popover.querySelector('[data-field-key="seed"]')!.className).toContain("grid-cols-[112px_minmax(0,1fr)]");
    expect(popover.querySelector('[data-field-key="lang"]')).toBeNull();
  });

  it("运行发出去的是这一格的产出者、配置和绑定", async () => {
    stubApi([{ value: "i1", label: "我的回声" }]);
    const run = vi.fn(async (_request: BoardRunRequest) => undefined);
    const host: ComposerHost = {
      item: action({ config: { mode: "b" }, bindings: { text: [{ from: "n1" }] } }),
      position: { x: 420, y: 10 },
      workspaceId: "w1",
      feeding: { ...NO_UPSTREAM, sources: [note("n1", "便签")] },
      documents: new Map(),
      models: [],
      writing: false,
      setWriting: () => undefined,
      onFormChange: () => undefined,
      onPickAsset: () => undefined,
      run,
      producers: [TOOL],
    };
    mount(<>{renderComposer("node:plugin.any.echo", host)}</>);
    await waitFor(() => expect(screen.getByText("boardToolConnection".replace("{name}", "我的回声"))).toBeTruthy());
    fireEvent.click(sendButton());
    await waitFor(() => expect(run).toHaveBeenCalledTimes(1));
    expect(run.mock.calls[0][0]).toEqual({
      producer: "node:plugin.any.echo",
      item_id: "a1",
      kind: "action",
      x: 420,
      y: 10,
      form: { config: { mode: "b" }, bindings: { text: [{ from: "n1" }] } },
    });
  });

  it("没有这个插件的连接:说清楚、给去插件页的入口,不让点运行", async () => {
    stubApi([]);
    mount(<Stateful initial={action()} sources={[]} />);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("boardToolNoConnection".replace("{plugin}", "我的回声"));
    expect(within(alert).getByRole("link", { name: "boardToolOpenPlugins" }).getAttribute("href")).toBe("#/plugins");
    expect(sendButton().disabled).toBe(true);
  });

  // 正文再长,发送键也不能被挤出面板:正文一格自己滚,底栏在滚动区**外面**、钉在面板底边。
  it("发送键不在滚动的正文里,钉在底栏", async () => {
    stubApi([{ value: "i1", label: "我的回声" }]);
    mount(<Stateful initial={action()} sources={[]} />);
    await waitFor(() => expect(sendButton()).toBeTruthy());
    const body = panel().querySelector<HTMLElement>("[data-board-composer-body]")!;
    expect(body.className).toContain("overflow-y-auto");
    expect(panel().className).not.toContain("overflow-y-auto");
    expect(panel().className).toContain("grid-rows-[minmax(0,1fr)_auto]");
    expect(body.contains(sendButton())).toBe(false);
    expect(sendButton().closest("[data-board-composer-bar]")?.parentElement).toBe(panel());
  });

  it("清单里没有这个工具(插件卸了、这个人没接):不给表单", () => {
    stubApi([]);
    mount(<Stateful initial={action()} sources={[]} tool={null} />);
    expect(screen.getByRole("alert").textContent).toContain("boardToolUnavailable");
    expect(document.querySelector("[data-board-composer-send]")).toBeNull();
  });
});

/**
 * 「渲染白模参考」那种工具:场景可以挑也可以接画布上的场景格,镜头跟着场景走。
 * 用户的原话是「有些应该是下拉选择而非输入吧」—— 此前这两格都是文本框,要去别处抄 id。
 */
describe("指向某样东西的字段是下拉", () => {
  const SCENE_TOOL = {
    ...TOOL,
    id: "node:scene_render",
    type: "scene_render",
    plugin_name: "",
    config: {
      scene_id: { type: "text", required: true, label: "3D 场景", data_type: "scene", options_from: "scenes",
                  board_sources: ["scene"] },
      shot_id: { type: "text", label: "镜头", depends_on: "scene_id", options_from: "scene_shots",
                 sole_option_default: true, board_sources: [] },
    },
  } as unknown as BoardProducerInfo;
  const sceneCell = (id: string, sceneId: string): BoardItem => ({ id, kind: "scene", x: 0, y: 0, scene_id: sceneId, title: id });

  function stubScenes() {
    const asked: string[] = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://x");
      const source = url.searchParams.get("source");
      const parent = url.searchParams.get("parent") ?? "";
      asked.push(`${source}:${parent}`);
      const body =
        source === "scenes"
          ? [{ value: "s1", label: "客厅" }, { value: "s2", label: "天台" }]
          : source === "scene_shots" && parent === "s1"
            ? [{ value: "shot-1", label: "开场" }, { value: "shot-2", label: "近景" }]
            : source === "scene_shots" && parent === "s2"
              ? [{ value: "roof-1", label: "俯拍" }]
              : [];
      return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    }) as never;
    return asked;
  }
  const chip = (key: string) => within(barField(key)!).getByRole("combobox");

  it("没接上游:场景和镜头都是底栏的下拉芯片;镜头按挑中的场景列,换场景清掉旧镜头", async () => {
    const asked = stubScenes();
    const saved: BoardItem["form"][] = [];
    mount(<Stateful initial={action({ config: { scene_id: "s1", shot_id: "shot-2" } })} sources={[]} tool={SCENE_TOOL}
                    onSaved={(form) => saved.push(form)} />);

    await waitFor(() => expect(chip("shot_id").textContent).toContain("近景"));
    expect(asked).toEqual(expect.arrayContaining(["scenes:", "scene_shots:s1"]));
    //: 挑一个,不是能随手敲字的输入框;画板上没有 `{{…}}` 引用可写。
    expect(document.querySelector('textarea[data-field-key="scene_id"], input')).toBeNull();

    fireEvent.keyDown(chip("scene_id"), { key: "Enter" });
    fireEvent.click(await screen.findByRole("option", { name: "天台" }));
    await waitFor(() => expect(saved.at(-1)?.config).toEqual({ scene_id: "s2", shot_id: "" }));
    //: 天台只有一个镜头:留空就是它,显示成当前值 —— 不替人写进配置(运行时同一条规矩)。
    await waitFor(() => expect(chip("shot_id").textContent).toContain("俯拍"));
    expect(saved.at(-1)?.config).toEqual({ scene_id: "s2", shot_id: "" });
  });

  it("场景接了画布上的场景格:场景那一格是上游芯片不是下拉,镜头按那一格的场景列;换接另一格清掉旧镜头", async () => {
    const asked = stubScenes();
    const saved: BoardItem["form"][] = [];
    mount(<Stateful initial={action({ config: { shot_id: "shot-2" }, bindings: { scene_id: [{ from: "c1" }] } })}
                    sources={[sceneCell("c1", "s1"), sceneCell("c2", "s2")]} tool={SCENE_TOOL}
                    onSaved={(form) => saved.push(form)} />);

    await waitFor(() => expect(chip("shot_id").textContent).toContain("近景"));
    expect(asked).toContain("scene_shots:s1");
    //: 接上了:挑场景的下拉让位给上游芯片,两个来源不会同时摆着。
    expect(barField("scene_id")).toBeNull();
    expect(chips("scene_id")).not.toBeNull();

    fireEvent.click(chips("scene_id")!.querySelector<HTMLElement>('[data-binding-source="c2"]')!);
    await waitFor(() => expect(saved.at(-1)).toMatchObject({
      bindings: { scene_id: [{ from: "c2" }] }, config: { shot_id: "" },
    }));
    await waitFor(() => expect(chip("shot_id").textContent).toContain("俯拍"));
    expect(asked).toContain("scene_shots:s2");
  });

  it("场景还没挑:镜头说先挑哪一格,是灰的", async () => {
    stubScenes();
    mount(<Stateful initial={action({ config: {} })} sources={[]} tool={SCENE_TOOL} />);
    await waitFor(() => expect(chip("shot_id").textContent).toContain("wfPickParentFirst"));
    expect(chip("shot_id")).toBeDisabled();
  });
});

describe("空槽的产出者切换", () => {
  const producer = (id: string, hosts: string[], fills = true) =>
    ({ ...TOOL, id, type: id, hosts, fills_empty_slot: fills }) as unknown as BoardProducerInfo;
  const registry = [producer("speak", ["audio"]), producer("generate", ["image", "video", "audio"]), producer("trim", ["video", "audio"], false)];

  it("一种格子有两个能填空槽的产出者时才给切换(截一段不算)", () => {
    const empty: BoardItem = { id: "s", kind: "audio", x: 0, y: 0, form: { producer: "speak" } };
    expect(slotProducers(empty, registry).map((one) => one.id)).toEqual(["speak", "generate"]);
    expect(slotProducers({ ...empty, kind: "image", form: { producer: "generate" } }, registry)).toEqual([]);
    expect(slotProducers({ ...empty, asset_id: "done" }, registry)).toEqual([]);
    expect(slotProducers(empty, undefined)).toEqual([]);
  });
});
