/** @vitest-environment jsdom */

/**
 * 「工作流里能填的」的节点分组标题:`#706` 不是一段死字,是一颗能点的按钮 —— 点了在画布上定位那个节点,和助手回复里的
 * `#12` 是同一颗(见 workbench/LocateNodeButton)。维护者要的就是这个:组名是用户起的,光看名字对不上画布上哪一个。
 *
 * 钉住四件事:
 *
 * - 每个节点分组都有一颗按钮,点了经桥 `locate` 这个节点(和缺失项的「定位」同一个桥调用);
 * - 桥说画布上没有这个节点,标题那一行照实说一句(那句话跟着这颗按钮走,不串到别的组);
 * - 「整张图」那一组没有节点可定位,不给按钮;
 * - 这一列旁边**不一定有画布**(工作流库里那个宽版编辑器旁边就没有):桥调不通时照实说它回的那一句,不假装定位成了。
 *
 * 还有这一处的规约:「一处只有一条说明」。说明挂在标题上(说的是这个节点是什么),按钮自己不再挂一条,它的名字走
 * aria-label —— 两条 Hint 叠在同一个地方是噪音。
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

//: 桥(主进程那一侧)记下来:这里只关心面板叫了它什么、它回了什么(见 workbenchSession.workbenchCall)
const bridge = vi.hoisted(() => ({
  workbenchCall: vi.fn(),
  /** 真的那一个,当默认实现用:没开着工作台、也没有桥时它回 `closed` */
  real: null as null | ((call: ComfyWorkbenchCall) => Promise<ComfyWorkbenchCallResult>),
}));

vi.mock("@/api/client", () => ({ getWorkflowApp: vi.fn(), annotateWorkflow: vi.fn(), getFormUsages: vi.fn() }));
vi.mock("@/app/preferences", async () => {
  //: 「在画布上定位 #706」「画布上没有节点 #706」这几句用真的中文文案拼(断言看的就是人眼看到的那句);别的照旧回键名
  const { messages } = await import("@/app/messages");
  const zh = messages["zh-CN"] as Record<string, string>;
  const t = (key: string) => (key.startsWith("workbenchAssistant") || key === "workbenchCallFailed" ? zh[key] : key);
  return { useI18n: () => t, translateNow: t, usePreferences: () => ({ locale: "zh" }) };
});
vi.mock("@/features/plugins/workbench/workbenchSession", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/features/plugins/workbench/workbenchSession")>();
  //: 默认行为就是真的那一个 —— 「旁边没有画布」那一条要验的是它(`closed`),不是这里现编一个原因码
  bridge.real = real.workbenchCall;
  return { ...real, workbenchCall: bridge.workbenchCall };
});

beforeEach(() => {
  //: 每条用例回到真的 workbenchCall;要造桥的回复的那几条自己 mockResolvedValue
  bridge.workbenchCall.mockReset();
  if (bridge.real) bridge.workbenchCall.mockImplementation(bridge.real);
});

import type { WorkflowApp } from "@/api/client";
import { SourcePanel } from "@/features/plugins/appForm/SourcePanel";
import type { FormDraft } from "@/features/plugins/workflowAppForm";
import { readHint } from "@/test/hint";

/** 这张工作流:两个节点各有一项能填的(名字是用户起的标题),加上「整张图」那一组的两项。 */
function data(): WorkflowApp {
  const base = { node_title: "", node_label: "", hint: "", role: "", media: "", folder: "",
                 common: true, exposable: true, unexposable_reason: "" };
  return {
    path: "遮罩.json",
    modified: 1,
    kind: "image",
    editable: true,
    items: [
      { ...base, key: "706.image", node: "706", input: "image", kind: "media", role: "reference_image", media: "image",
        title: "输入图", node_label: "Draw Mask On Image", class_type: "DrawMaskOnImage", spec: null },
      { ...base, key: "720.strength", node: "720", input: "strength", kind: "number", title: "裁切范围",
        node_label: "Inpaint Crop", class_type: "InpaintCrop", spec: { type: "number", default: 0 } },
      { ...base, key: "seed", node: "", input: "seed", kind: "seed", title: "种子", class_type: "KSampler", spec: null },
      { ...base, key: "runs", node: "", input: "runs", kind: "runs", title: "跑几遍", class_type: "", spec: null },
    ],
    outputs: [],
    app: { status: "none", version: "", upgradable: false, forms: [], results: [], invalid: 0, stray: 0 },
  } as WorkflowApp;
}

/** 表单还是空的:左边那一列的每一行都还是「+」。 */
function draft(): FormDraft {
  return { id: "", key: "new-1", title: "遮罩", description: "", model: "", tool: "", items: [] };
}

function show(items?: WorkflowApp["items"]) {
  const base = data();
  render(<SourcePanel data={items ? { ...base, items } : base} draft={draft()} onAdd={() => {}} onRemove={() => {}} />);
  //: 一个节点一组;「整张图」那一组的节点号是空的(data-source-group="")
  const group = (node: string) => document.querySelector(`[data-source-group="${node}"]`) as HTMLElement;
  const chip = (container: HTMLElement) => container.querySelector("button[data-comfy-node]") as HTMLButtonElement | null;
  const heading = (container: HTMLElement) => container.querySelector("h5") as HTMLElement;
  return { group, chip, heading };
}

describe("「工作流里能填的」:节点分组标题上的节点号能在画布上定位", () => {
  it("每个节点分组都有一颗按钮:点了经桥定位这个节点", async () => {
    bridge.workbenchCall.mockResolvedValue({ ok: true });
    const { group, chip, heading } = show();

    const first = chip(group("706"))!;
    //: 它在标题那一行里、紧挨着名字;名字是用户起的,只有这一颗按钮说得清这是画布上的哪一个
    expect(heading(group("706")).textContent).toBe("Draw Mask On Image#706");
    expect(first.textContent).toBe("#706");
    //: 长相按这一处来(标题那一档的正文字号和次要色),不是回复里那条链接的样子 —— 同一颗按钮两种场合,
    //: 靠 cn 里后写的赢(见 lib/utils;这里也钉住那几个 class 没被悄悄丢掉)
    expect(first.className).toContain("text-ui-xs");
    expect(first.className).not.toContain("text-[0.95em]");
    expect(first.className).not.toContain("font-mono");
    //: 读屏和键盘用户听到的不是孤零零一个「#706」
    expect(first.getAttribute("aria-label")).toBe("在画布上定位 #706");

    fireEvent.click(first);
    await waitFor(() => expect(bridge.workbenchCall).toHaveBeenCalledWith({ op: "locate", node: "706", subgraph: null }));

    fireEvent.click(chip(group("720"))!);
    await waitFor(() => expect(bridge.workbenchCall).toHaveBeenCalledWith({ op: "locate", node: "720", subgraph: null }));
    //: 成了就不留话
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("桥说画布上没有这个节点:标题那一行照实说一句(不串到旁边那一组)", async () => {
    bridge.workbenchCall.mockResolvedValue({ ok: false, error: "noNode" });
    const { group, chip } = show();

    expect(screen.queryByRole("status")).toBeNull();
    fireEvent.click(chip(group("706"))!);
    expect(await screen.findByRole("status")).toHaveProperty("textContent", "画布上没有节点 #706");
    expect(group("706").contains(screen.getByRole("status"))).toBe(true);
    expect(group("720").contains(screen.getByRole("status"))).toBe(false);
  });

  it("旁边没有画布(工作流库里那个宽版编辑器):照实说一句人话,不假装定位成了", async () => {
    //: 这一条**不造假**:走的是真的 workbenchCall —— 没开着工作台时它连桥都够不着,回 `closed`(见 workbenchSession)。
    //: 界面上说的是「还没连上画布」,不是把原因码 `closed` 摆到人眼前(读的人不知道那是什么)。
    const { group, chip } = show();

    fireEvent.click(chip(group("720"))!);
    expect(await screen.findByRole("status")).toHaveProperty("textContent", "还没连上画布");
  });

  it("「整张图」那一组没有节点可定位:不给按钮", () => {
    const { group, chip } = show();

    const graph = group("");
    expect(graph.querySelectorAll("[data-source-item]")).toHaveLength(2);
    expect(chip(graph)).toBeNull();
    expect(graph.querySelector("h5")!.textContent).toBe("workflowAppGraphGroup");
    //: 别的组照常各有一颗
    expect(chip(group("706"))).not.toBeNull();
    expect(chip(group("720"))).not.toBeNull();
  });

  it("按钮不自己再挂一条说明:标题那一行只有一条(说的是这个节点是什么)", () => {
    const { group, chip, heading } = show();

    //: 说明的触发器是标题这一条(Hint 标出来的);里面不再有第二条(被截断的全文并进这一条,按钮也不挂)
    expect(heading(group("720")).hasAttribute("data-hint-trigger")).toBe(true);
    expect(heading(group("720")).querySelectorAll("[data-hint-trigger]")).toHaveLength(0);
    expect(chip(group("720"))!.hasAttribute("data-hint-trigger")).toBe(false);
  });
});

/**
 * 「蒙版属性」那一组:插件沿 MASK 这条线走出来的几格(ADR 0056 第一步,见 graph.mask_path)——
 * `mask_property` 是它在**这条线上的第几位**(1 起数),不是一个是非:这一列本身的顺序是常用程度,
 * 那一组要按沿线的先后摆(来源 → 蒙版运算 → 送给采样器)。名字照旧只用插件给的 `title` / `hint` / `node_label`。
 */
function maskItems(): WorkflowApp["items"] {
  const base = { node_title: "", node_label: "", hint: "", role: "", media: "", folder: "",
                 common: true, exposable: true, unexposable_reason: "" };
  return [
    { ...base, key: "11.image", node: "11", input: "image", kind: "media", role: "mask", media: "mask",
      title: "蒙版 · 加载图像(作为蒙版) #11", node_label: "加载图像(作为蒙版)", class_type: "LoadImageMask",
      mask_property: 1, spec: null },
    //: 类名和控件名都是插件那边编的:认的是连线上的类型,界面这边一个名字都不认
    { ...base, key: "30.grow_px", node: "30", input: "grow_px", kind: "number", title: "MyCustomMaskGrow · Grow px",
      node_label: "MyCustomMaskGrow", class_type: "MyCustomMaskGrow", mask_property: 2,
      spec: { type: "integer", default: 8 } },
    { ...base, key: "20.softness", node: "20", input: "softness", kind: "number", title: "MyCustomMaskFeather · Softness",
      node_label: "MyCustomMaskFeather", class_type: "MyCustomMaskFeather", mask_property: 3,
      spec: { type: "number", default: 2 } },
    //: 名字里带 mask 的普通项(吃的是 IMAGE):它不进那一组,照旧在自己的节点分组里
    { ...base, key: "40.quality", node: "40", input: "quality", kind: "number", title: "MaskSaver · Quality",
      node_label: "MaskSaver", class_type: "MaskSaver", spec: { type: "integer", default: 90 } },
    { ...base, key: "3.steps", node: "3", input: "steps", kind: "number", title: "步数", node_label: "K 采样器",
      class_type: "KSampler", spec: { type: "integer", default: 20 } },
  ];
}

describe("「蒙版属性」自成一组", () => {
  it("在组里的是蒙版属性,普通项不在;顺序照插件给的第几位(不是节点号)", () => {
    const { group, chip } = show(maskItems());

    const mask = group("mask");
    const rows = [...mask.querySelectorAll("[data-source-item]")].map((one) => one.getAttribute("data-source-item"));
    //: 沿线是 11 → 30 → 20,而节点号是乱的(30 在 20 前面)、这一列里排的顺序也不是这个
    expect(rows).toEqual(["11.image", "30.grow_px", "20.softness"]);
    //: 那一组不是一个节点:标题是界面自己的那句话,没有可定位的节点号
    expect(mask.querySelector("h5")!.textContent).toBe("workflowAppMaskGroup");
    expect(chip(mask)).toBeNull();
    //: 普通项照旧各在自己的节点分组里(MaskSaver 名字里带 mask 也不算)
    expect(group("40").querySelectorAll("[data-source-item]")).toHaveLength(1);
    expect(group("3").querySelectorAll("[data-source-item]")).toHaveLength(1);
    expect(mask.querySelector('[data-source-item="40.quality"]')).toBeNull();
    expect(mask.querySelector('[data-source-item="3.steps"]')).toBeNull();
  });

  it("那一组的行照 title 显示几个节点的格子混在一起,节点名不能像别的组那样去掉", () => {
    const { group } = show(maskItems());
    const shown = (key: string) => group("mask").querySelector(`[data-source-item="${key}"]`)!.textContent!;

    expect(shown("30.grow_px")).toContain("MyCustomMaskGrow · Grow px");
    expect(shown("20.softness")).toContain("MyCustomMaskFeather · Softness");
    expect(shown("11.image")).toContain("蒙版 · 加载图像(作为蒙版) #11");
    //: 按节点分的那几组照旧去掉名字里重复的节点名(MaskSaver · Quality → Quality)
    expect(group("40").textContent).toContain("Quality");
    expect(group("40").textContent).not.toContain("MaskSaver · Quality");
  });

  it("没有蒙版属性时不多出这一组", () => {
    const { group } = show();
    expect(group("mask")).toBeNull();
  });
});

/**
 * 子图里面的节点(`12:5`,ADR 0042 的写法)和根图上的节点一样能放进表单 —— 维护者报的那条能力缺口就是它。
 * 灰着的只剩插件说**不能**的那几项(那份子图在这张图里用了不止一处,节点指不明是哪一处),而且理由由插件给:
 * 说清为什么、该怎么办,不是界面上一句「这一版不支持」。
 */
function subgraphItems(): NonNullable<WorkflowApp["items"]> {
  const base = { node_title: "", node_label: "", hint: "", role: "", media: "", folder: "",
                 common: true, exposable: true, unexposable_reason: "" };
  return [
    { ...base, key: "12:5.steps", node: "12:5", input: "steps", kind: "number", title: "步数", node_label: "采样 · 采样",
      class_type: "KSampler", spec: { type: "integer", default: 20 } },
    { ...base, key: "12:5.cfg", node: "12:5", input: "cfg", kind: "number", title: "CFG", node_label: "采样 · 采样",
      class_type: "KSampler", spec: { type: "number", default: 7 } },
    { ...base, key: "20:5.steps", node: "20:5", input: "steps", kind: "number", title: "步数", node_label: "采样 2 · 采样",
      class_type: "KSampler", exposable: false,
      unexposable_reason: "子图「采样」在这张图里用了 2 处,里面的节点只能按第一处写(#12:5)—— 要放进表单:先在画布上把它拆开,或者只留一处",
      spec: { type: "integer", default: 20 } },
  ];
}

describe("子图里面的节点也能放进表单", () => {
  it("加得进去,键就是那个节点路径(12:5.steps)", () => {
    const added: string[] = [];
    const base = data();
    render(<SourcePanel data={{ ...base, items: subgraphItems() }} draft={draft()}
                        onAdd={(item) => added.push(item.key)} onRemove={() => {}} />);
    const row = (key: string) => document.querySelector(`[data-source-item="${key}"]`) as HTMLElement;
    const plus = (key: string) => row(key).querySelector("button") as HTMLButtonElement;

    expect(plus("12:5.steps").disabled, "子图里面的节点不再是灰的").toBe(false);
    fireEvent.click(plus("12:5.steps"));
    expect(added, "加的是里面那个节点上的那一格,不是外面那个子图节点上的").toEqual(["12:5.steps"]);
  });

  it("插件说不能的那一项灰着,理由说的是为什么、该怎么办(不是「这一版不支持」)", async () => {
    const base = data();
    render(<SourcePanel data={{ ...base, items: subgraphItems() }} draft={draft()} onAdd={() => {}} onRemove={() => {}} />);
    const row = document.querySelector('[data-source-item="20:5.steps"]') as HTMLElement;
    const plus = row.querySelector("button") as HTMLButtonElement;

    expect(plus.disabled).toBe(true);
    const said = await readHint(plus);
    expect(said).toContain("用了 2 处");
    expect(said).toContain("#12:5");
    expect(said).toContain("拆开");
  });

  it("插件没给理由时说一句通用的,不把按钮留成哑的", async () => {
    const base = data();
    const bare = { ...subgraphItems()[2]!, unexposable_reason: "" };
    render(<SourcePanel data={{ ...base, items: [bare] }} draft={draft()} onAdd={() => {}} onRemove={() => {}} />);
    const plus = document.querySelector('[data-source-item="20:5.steps"] button') as HTMLButtonElement;

    expect(plus.disabled).toBe(true);
    expect(await readHint(plus)).toContain("workflowAppNotExposable");
  });
});
