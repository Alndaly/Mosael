/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

/**
 * 工具格的面板:表单照节点声明长出来,画板只补两件自己的事 —— 字段接上游(芯片,按后端给的
 * `board_sources` 过滤)和「用谁的连接」。
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

describe("工具格的面板", () => {
  it("必填的文字字段默认接上第一张便签;芯片只列接得上的上游,点一下就存", async () => {
    stubApi([{ value: "i1", label: "我的回声" }]);
    const saved: BoardItem["form"][] = [];
    mount(<Stateful initial={action()} sources={[picture, note("n1", "第一张"), note("n2", "第二张")]} onSaved={(form) => saved.push(form)} />);

    await waitFor(() => expect(saved[0]?.bindings).toEqual({ text: [{ from: "n1" }] }));
    const text = document.querySelector<HTMLElement>('[data-field-key="text"]')!;
    const chips = within(text).getAllByRole("button", { pressed: undefined }).filter((one) => one.dataset.bindingSource);
    //: 文字字段只接便签和文档 —— 图片不在这一排里。
    expect(chips.map((one) => one.dataset.bindingSource)).toEqual(["n1", "n2"]);
    expect(chips[0].getAttribute("aria-pressed")).toBe("true");

    //: 文字字段收一串:再点一张,两张都接上(运行时按连线顺序拼起来)。
    fireEvent.click(chips[1]);
    expect(saved.at(-1)?.bindings).toEqual({ text: [{ from: "n1" }, { from: "n2" }] });

    //: 素材字段不是必填,不默认接;点开「接上游」,接的是图片。
    const pictureField = document.querySelector<HTMLElement>('[data-field-key="picture"]')!;
    fireEvent.click(within(pictureField).getByText("wfInputManual"));
    expect(saved.at(-1)?.bindings).toEqual({ text: [{ from: "n1" }, { from: "n2" }], picture: [{ from: "img" }] });
    //: 固定选项的字段没有「接上游」。
    const mode = document.querySelector<HTMLElement>('[data-field-key="mode"]')!;
    expect(within(mode).queryByText("wfInputManual")).toBeNull();
  });

  it("切回手填之后不会又被默认绑回去", async () => {
    stubApi([{ value: "i1", label: "我的回声" }]);
    const saved: BoardItem["form"][] = [];
    mount(<Stateful initial={action({ bindings: { text: [{ from: "n1" }] } })} sources={[note("n1", "便签")]} onSaved={(form) => saved.push(form)} />);
    const text = document.querySelector<HTMLElement>('[data-field-key="text"]')!;
    fireEvent.click(within(text).getByText("wfInputRef"));
    await waitFor(() => expect(saved.at(-1)).toMatchObject({ bindings: {}, config: { text: "" } }));
    expect(defaultBindings(TOOL.config as never, { text: "" }, {}, [note("n1", "便签")])).toBeNull();
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
    fireEvent.click(document.querySelector<HTMLElement>("[data-board-tool-run]")!);
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
    expect(document.querySelector<HTMLButtonElement>("[data-board-tool-run]")!.disabled).toBe(true);
  });

  // 展开「高级选项」时「运行」不能被挤出面板:正文一格自己滚,底栏在滚动区**外面**、钉在面板底边。
  it("运行那一行不在滚动的正文里,展开多少字段都钉在底部", async () => {
    stubApi([{ value: "i1", label: "我的回声" }]);
    mount(<Stateful initial={action()} sources={[]} />);
    const run = await waitFor(() => document.querySelector<HTMLElement>("[data-board-tool-run]")!);
    const panel = document.querySelector<HTMLElement>("[data-action-composer]")!;
    const body = panel.querySelector<HTMLElement>("[data-action-composer-body]")!;
    expect(body.className).toContain("overflow-y-auto");
    expect(panel.className).not.toContain("overflow-y-auto");
    expect(body.contains(run)).toBe(false);
    expect(run.closest("[data-action-composer-footer]")?.parentElement).toBe(panel);
  });

  it("清单里没有这个工具(插件卸了、这个人没接):不给表单", () => {
    stubApi([]);
    mount(<Stateful initial={action()} sources={[]} tool={null} />);
    expect(screen.getByRole("alert").textContent).toContain("boardToolUnavailable");
    expect(document.querySelector("[data-board-tool-run]")).toBeNull();
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
  const field = (key: string) => document.querySelector<HTMLElement>(`[data-field-key="${key}"]`)!;

  it("没接上游:场景和镜头都是标准下拉;镜头按挑中的场景列,换场景清掉旧镜头", async () => {
    const asked = stubScenes();
    const saved: BoardItem["form"][] = [];
    mount(<Stateful initial={action({ config: { scene_id: "s1", shot_id: "shot-2" } })} sources={[]} tool={SCENE_TOOL}
                    onSaved={(form) => saved.push(form)} />);

    await waitFor(() => expect(within(field("shot_id")).getByRole("combobox").textContent).toContain("近景"));
    expect(asked).toEqual(expect.arrayContaining(["scenes:", "scene_shots:s1"]));
    //: 标准下拉(Select),不是能随手敲字的输入框;画板上没有 `{{…}}` 引用可写。
    expect(field("scene_id").querySelector("textarea, input")).toBeNull();
    expect(field("shot_id").querySelector("textarea, input")).toBeNull();

    fireEvent.keyDown(within(field("scene_id")).getByRole("combobox"), { key: "Enter" });
    fireEvent.click(await screen.findByRole("option", { name: "天台" }));
    await waitFor(() => expect(saved.at(-1)?.config).toEqual({ scene_id: "s2", shot_id: "" }));
    //: 天台只有一个镜头:留空就是它,显示成当前值 —— 不替人写进配置(运行时同一条规矩)。
    await waitFor(() => expect(within(field("shot_id")).getByRole("combobox").textContent).toContain("俯拍"));
    expect(saved.at(-1)?.config).toEqual({ scene_id: "s2", shot_id: "" });
  });

  it("场景接了画布上的场景格:场景那一格是芯片不是下拉,镜头按那一格的场景列;换接另一格清掉旧镜头", async () => {
    const asked = stubScenes();
    const saved: BoardItem["form"][] = [];
    mount(<Stateful initial={action({ config: { shot_id: "shot-2" }, bindings: { scene_id: [{ from: "c1" }] } })}
                    sources={[sceneCell("c1", "s1"), sceneCell("c2", "s2")]} tool={SCENE_TOOL}
                    onSaved={(form) => saved.push(form)} />);

    await waitFor(() => expect(within(field("shot_id")).getByRole("combobox").textContent).toContain("近景"));
    expect(asked).toContain("scene_shots:s1");
    //: 接上了:挑场景的下拉让位给上游芯片,两个来源不会同时摆着。
    expect(within(field("scene_id")).queryByRole("combobox")).toBeNull();
    expect(field("scene_id").querySelector("[data-binding-chips]")).not.toBeNull();

    fireEvent.click(field("scene_id").querySelector<HTMLElement>('[data-binding-source="c2"]')!);
    await waitFor(() => expect(saved.at(-1)).toMatchObject({
      bindings: { scene_id: [{ from: "c2" }] }, config: { shot_id: "" },
    }));
    await waitFor(() => expect(within(field("shot_id")).getByRole("combobox").textContent).toContain("俯拍"));
    expect(asked).toContain("scene_shots:s2");
  });

  it("场景还没挑:镜头说先挑哪一格,是灰的", async () => {
    stubScenes();
    mount(<Stateful initial={action({ config: {} })} sources={[]} tool={SCENE_TOOL} />);
    await waitFor(() => expect(within(field("shot_id")).getByRole("combobox").textContent).toContain("wfPickParentFirst"));
    expect(within(field("shot_id")).getByRole("combobox")).toBeDisabled();
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
