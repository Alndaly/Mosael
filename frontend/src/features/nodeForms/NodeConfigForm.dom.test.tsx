/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

/**
 * 节点表单离开工作流也能用:没有图、没有数据边,只给声明和配置。
 *
 * 创意画板上「跑一个工具」的格子就是这种宿主 —— 它要的是同一张表单(同样的下拉来源、同样的
 * 基础 / 高级分档、同样按素材类型给素材),而不是再抄一份。这里用的节点类型名是假的,钉住
 * 「表单不认识具体节点」。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { TooltipProvider } from "@/components/ui/tooltip";
import {
  NodeConfigForm,
  nodeConfigTiers,
  useNodeFieldOptions,
  type ConfigSpec,
} from "@/features/nodeForms/NodeConfigForm";

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

//: 形状和 /api/workflows/node-types 发下来的一样(label、data_type 由后端贴好)。
const SPECS = {
  video: { type: "template", required: true, label: "视频", data_type: "asset" },
  platform: { type: "string", options_from: "some_source", label: "平台" },
  page: { type: "number", advanced: true, label: "页码" },
  expert: { type: "string", active_when: { platform: "x" }, label: "只对 x 有用" },
} as unknown as Record<string, ConfigSpec>;

function Host({ config }: { config: Record<string, unknown> }) {
  const fieldOptions = useNodeFieldOptions({ specs: SPECS, config, workspaceId: "w1", nodeType: "plugin.any.tool" });
  const { basic } = nodeConfigTiers(SPECS, config);
  return (
    <NodeConfigForm
      fields={basic}
      config={config}
      workspaceId="w1"
      variables={[]}
      fieldOptions={fieldOptions}
      onSetConfig={vi.fn()}
      onTypeConfig={vi.fn()}
    />
  );
}

function renderForm(config: Record<string, unknown>) {
  const asked: string[] = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://x");
    let body: unknown = [];
    if (url.pathname.endsWith("/workflows/field-options")) {
      asked.push(`${url.searchParams.get("source")}:${url.searchParams.get("node_type")}`);
      body = [{ value: "x", label: "X 平台" }];
    } else if (url.pathname.endsWith("/assets")) {
      asked.push("assets");
      body = [{ id: "a1", name: "开场.mp4", original_filename: "open.mp4" }];
    }
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  }) as never;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <Host config={config} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return { asked };
}

const fieldKeys = () =>
  Array.from(document.querySelectorAll<HTMLElement>("[data-field-key]")).map((el) => el.dataset.fieldKey);

describe("节点表单", () => {
  it("高级项和此刻不参与的字段都不在基础档里", () => {
    expect(nodeConfigTiers(SPECS, {}).basic.map(([key]) => key)).toEqual(["video", "platform"]);
    expect(nodeConfigTiers(SPECS, {}).advanced.map(([key]) => key)).toEqual(["page"]);
    expect(nodeConfigTiers(SPECS, { platform: "x" }).basic.map(([key]) => key)).toEqual(["video", "platform", "expert"]);
    expect(nodeConfigTiers(SPECS, {}, (key) => key === "video").basic.map(([key]) => key)).toEqual(["platform"]);
  });

  it("没有宿主的连线时,字段只有手填 / 下拉,不给「接上游」的开关", async () => {
    renderForm({});
    await waitFor(() => expect(fieldKeys()).toEqual(["video", "platform"]));
    expect(document.body.textContent).not.toContain("wfInputManual");
  });

  it("text 字段就是一段字:一个普通的文本框,`{{…}}` 原样是字,不变成引用标签(画板上的模板字段)", () => {
    const specs = { caption: { type: "text", label: "文案", multiline: true } } as unknown as Record<string, ConfigSpec>;
    const onType = vi.fn();
    render(
      <QueryClientProvider client={new QueryClient()}>
        <NodeConfigForm
          fields={Object.entries(specs)}
          config={{ caption: "写 {{不是引用}}" }}
          workspaceId="w1"
          variables={[]}
          fieldOptions={{ dynamicOptions: () => null, whyEmpty: () => ({ kind: "none" }), assets: [] }}
          onSetConfig={vi.fn()}
          onTypeConfig={onType}
        />
      </QueryClientProvider>,
    );
    const field = document.querySelector<HTMLElement>('[data-field-key="caption"]')!;
    const box = within(field).getByRole("textbox") as HTMLTextAreaElement;
    expect(box.tagName).toBe("TEXTAREA");
    expect(box.rows).toBe(4);
    expect(box.value).toBe("写 {{不是引用}}");
  });

  describe("挑一样东西(场景 → 镜头)", () => {
    //: 形状和 scene_render 的声明一样,但用的是假节点名 —— 表单只认声明。
    const PICK = {
      scene: { type: "template", required: true, label: "3D 场景", options_from: "scenes" },
      shot: { type: "template", label: "镜头", depends_on: "scene", options_from: "scene_shots", sole_option_default: true },
    } as unknown as Record<string, ConfigSpec>;

    function PickHost({ config, references, boundValues, variables = [], onSet = vi.fn() }: {
      config: Record<string, unknown>;
      references?: boolean;
      boundValues?: Record<string, string>;
      variables?: string[];
      onSet?: (key: string, value: unknown) => void;
    }) {
      const fieldOptions = useNodeFieldOptions({ specs: PICK, config, workspaceId: "w1", nodeType: "x.render", boundValues });
      return (
        <NodeConfigForm
          fields={Object.entries(PICK)}
          config={config}
          workspaceId="w1"
          variables={variables}
          fieldOptions={fieldOptions}
          onSetConfig={onSet}
          onTypeConfig={onSet}
          references={references}
        />
      );
    }

    function mountPick(props: React.ComponentProps<typeof PickHost>) {
      const asked: string[] = [];
      globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
        const url = new URL(String(input), "http://x");
        const source = url.searchParams.get("source");
        const parent = url.searchParams.get("parent") ?? "";
        asked.push(`${source}:${parent}`);
        const body = source === "scenes"
          ? [{ value: "s1", label: "客厅" }]
          : parent === "s1" ? [{ value: "shot-1", label: "开场" }] : [];
        return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
      }) as never;
      render(
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <TooltipProvider>
            <PickHost {...props} />
          </TooltipProvider>
        </QueryClientProvider>,
      );
      return { asked };
    }
    const trigger = (key: string) =>
      within(document.querySelector<HTMLElement>(`[data-field-key="${key}"]`)!).getByRole("combobox");

    it("只有一个镜头:留空就显示它,不替人写进配置", async () => {
      const onSet = vi.fn();
      const { asked } = mountPick({ config: { scene: "s1" }, onSet });
      await waitFor(() => expect(trigger("shot").textContent).toContain("开场"));
      expect(asked).toContain("scene_shots:s1");
      expect(onSet).not.toHaveBeenCalled();
    });

    it("场景接的是上游:值到运行时才有,不去查,说清楚", async () => {
      const { asked } = mountPick({ config: {}, boundValues: { scene: "" } });
      await waitFor(() => expect(trigger("shot").textContent).toContain("wfParentFromUpstream"));
      expect(asked.some((one) => one.startsWith("scene_shots"))).toBe(false);
      expect(trigger("shot")).toBeDisabled();
    });

    it("场景是一段 `{{…}}` 引用时同样不查:那不是一个场景 id", async () => {
      const { asked } = mountPick({ config: { scene: "{{input.scene_id}}" }, references: true });
      await waitFor(() => expect(trigger("shot").textContent).toContain("wfParentFromUpstream"));
      expect(asked.some((one) => one.startsWith("scene_shots"))).toBe(false);
    });

    it("工作流里:清单后面列上游的输出,手敲只收引用,存着的引用原样显示", async () => {
      const user = userEvent.setup();
      const onSet = vi.fn();
      mountPick({
        config: { shot: "shot-{{loop.item.n}}" },
        references: true,
        variables: ["{{build.scene_id}}"],
        onSet,
      });
      //: 官方模板里写的是 `shot-{{loop.item.shot_number}}` —— 下拉不能把它显示成空白。
      expect(trigger("shot").textContent).toContain("shot-{{loop.item.n}}");

      await user.click(trigger("scene"));
      expect(await screen.findByRole("option", { name: /客厅/ })).toBeTruthy();
      expect(screen.getByRole("option", { name: /build\.scene_id/ })).toBeTruthy();
      //: 随手敲一串字不是一个场景:不给「使用」。
      await user.keyboard("随便写写");
      expect(screen.queryByText(/wfUseReference/)).toBeNull();
      await user.clear(document.querySelector<HTMLInputElement>("[cmdk-input]")!);
      await user.keyboard("{{{{input.scene_id}}");
      await user.click(await screen.findByText(/wfUseReference/));
      expect(onSet).toHaveBeenLastCalledWith("scene", "{{input.scene_id}}");
    });
  });

  it("素材字段声明了收哪几种(转写:音频和视频),下拉只列那几种", async () => {
    const specs = { clip: { type: "text", label: "音视频", data_type: "asset", media: ["audio", "video"] } } as unknown as Record<string, ConfigSpec>;
    globalThis.fetch = vi.fn(async () => new Response(JSON.stringify([
      { id: "i1", name: "封面.png", kind: "image" },
      { id: "a1", name: "口播.wav", kind: "audio" },
      { id: "v1", name: "开场.mp4", kind: "video" },
    ]), { status: 200, headers: { "content-type": "application/json" } })) as never;
    function MediaHost() {
      const fieldOptions = useNodeFieldOptions({ specs, config: {}, workspaceId: "w1", nodeType: "x.transcribe" });
      return (
        <NodeConfigForm fields={Object.entries(specs)} config={{}} workspaceId="w1" variables={[]}
                        fieldOptions={fieldOptions} onSetConfig={vi.fn()} onTypeConfig={vi.fn()} />
      );
    }
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MediaHost />
      </QueryClientProvider>,
    );
    const trigger = within(document.querySelector<HTMLElement>('[data-field-key="clip"]')!).getByRole("combobox");
    await waitFor(() => expect(trigger).not.toBeDisabled());
    fireEvent.keyDown(trigger, { key: "Enter" });
    expect(await screen.findByRole("option", { name: "口播.wav" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "开场.mp4" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: "封面.png" })).toBeNull();
  });

  it("下拉按声明去问后端,素材型字段给工作区素材", async () => {
    const { asked } = renderForm({ video: "a1" });
    await waitFor(() => expect(asked).toEqual(expect.arrayContaining(["some_source:plugin.any.tool", "assets"])));
    const video = document.querySelector<HTMLElement>('[data-field-key="video"]')!;
    await waitFor(() => expect(within(video).getByRole("combobox").textContent).toContain("开场.mp4"));
  });
});
