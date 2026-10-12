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
 *
 * 底下那一组钉住**名字是一组多语言的事实**:插件交回的是 `{"zh", "en"}` 一眼的表,挑哪一种由界面按自己的语言做。
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
//: 界面语言这一条用例里会换(名字是一张语言表,挑哪一种就看它)
const prefs = vi.hoisted(() => ({ locale: "zh" }));
vi.mock("@/app/preferences", async () => {
  //: 「在画布上定位 #706」「画布上没有节点 #706」这几句用真的中文文案拼(断言看的就是人眼看到的那句);别的照旧回键名
  const { messages } = await import("@/app/messages");
  const zh = messages["zh-CN"] as Record<string, string>;
  const t = (key: string) => (key.startsWith("workbenchAssistant") || key === "workbenchCallFailed" ? zh[key] : key);
  return { useI18n: () => t, translateNow: t, usePreferences: () => prefs };
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
  prefs.locale = "zh";
});

import type { WorkflowApp } from "@/api/client";
import { SourcePanel } from "@/features/plugins/appForm/SourcePanel";
import type { FormDraft } from "@/features/plugins/workflowAppForm";

/** 这张工作流:两个节点各有一项能填的(名字是用户起的标题),加上「整张图」那一组的两项。
 *  名字是**一句或一张语言表**两种形状都有:`title` / `node_label` 交回一对的走表,只给一句的就是那一句。 */
function data(): WorkflowApp {
  const base = { node_title: "", node_label: "", hint: "", role: "", media: "", folder: "",
                 common: true, exposable: true };
  return {
    path: "遮罩.json",
    modified: 1,
    kind: "image",
    editable: true,
    items: [
      { ...base, key: "706.image", node: "706", input: "image", kind: "media", role: "reference_image", media: "image",
        title: { zh: "输入图", en: "Input image" }, node_label: { zh: "在图上画蒙版", en: "Draw Mask On Image" },
        class_type: "DrawMaskOnImage", spec: null },
      { ...base, key: "720.strength", node: "720", input: "strength", kind: "number",
        title: { zh: "裁切范围", en: "Crop amount" },
        node_label: { zh: "修补裁切", en: "Inpaint Crop" }, class_type: "InpaintCrop", spec: { type: "number", default: 0 } },
      { ...base, key: "seed", node: "", input: "seed", kind: "seed", title: { zh: "种子", en: "Seed" },
        class_type: "KSampler", spec: null },
      //: 名字本来就只有一句的(插件只给了字符串):原样透出,不用挑
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
    expect(heading(group("706")).textContent).toBe("在图上画蒙版#706");
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
                 common: true, exposable: true };
  return [
    { ...base, key: "11.image", node: "11", input: "image", kind: "media", role: "mask", media: "mask",
      title: { zh: "蒙版 · 加载图像(作为蒙版) #11", en: "Mask · Load Image (as Mask) #11" },
      node_label: { zh: "加载图像(作为蒙版)", en: "Load Image (as Mask)" }, class_type: "LoadImageMask",
      mask_property: 1, spec: null },
    //: 类名和控件名都是插件那边编的:认的是连线上的类型,界面这边一个名字都不认
    { ...base, key: "30.grow_px", node: "30", input: "grow_px", kind: "number",
      title: { zh: "MyCustomMaskGrow · Grow px", en: "MyCustomMaskGrow · Grow px" },
      node_label: { zh: "MyCustomMaskGrow", en: "MyCustomMaskGrow" }, class_type: "MyCustomMaskGrow", mask_property: 2,
      spec: { type: "integer", default: 8 } },
    { ...base, key: "20.softness", node: "20", input: "softness", kind: "number",
      title: { zh: "MyCustomMaskFeather · Softness", en: "MyCustomMaskFeather · Softness" },
      node_label: { zh: "MyCustomMaskFeather", en: "MyCustomMaskFeather" }, class_type: "MyCustomMaskFeather",
      mask_property: 3, spec: { type: "number", default: 2 } },
    //: 名字里带 mask 的普通项(吃的是 IMAGE):它不进那一组,照旧在自己的节点分组里
    { ...base, key: "40.quality", node: "40", input: "quality", kind: "number",
      title: { zh: "MaskSaver · Quality", en: "MaskSaver · Quality" },
      node_label: { zh: "MaskSaver", en: "MaskSaver" }, class_type: "MaskSaver", spec: { type: "integer", default: 90 } },
    { ...base, key: "3.steps", node: "3", input: "steps", kind: "number", title: { zh: "步数", en: "Steps" },
      node_label: { zh: "K 采样器", en: "KSampler" },
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
 * 名字是**一组多语言的事实**,挑哪一种语言是界面的事(见 lib/pickLabel):插件交回的 `title` / `node_label` 是一句
 * 或一张 `{"zh", "en"}` 表,这里按界面的语言挑一句显示 —— 换语言,显示的就换一种。此前是后端在边界上塌成一句,
 * 换语言只能重取一遍,而且塌掉的那几种语言在数据里就没了(搜索也就搜不到)。
 */
function showAgain(items?: WorkflowApp["items"]) {
  const shown = items ? { ...data(), items } : data();
  const view = render(<SourcePanel data={shown} draft={draft()} onAdd={() => {}} onRemove={() => {}} />);
  //: 换语言:偏好变了重新渲染一遍(真的那一个走了 PreferencesProvider,组件跟着重渲染)
  const setLocale = (next: string) => {
    prefs.locale = next;
    view.rerender(<SourcePanel data={shown} draft={draft()} onAdd={() => {}} onRemove={() => {}} />);
  };
  return { setLocale };
}

describe("名字按界面语言挑一句显示", () => {
  it("界面是中文显示中文那一份;换成英文显示英文那一份", () => {
    const { setLocale } = showAgain();
    const rows = () => [...document.querySelectorAll("[data-source-item]")].map((one) => one.textContent ?? "");

    expect(rows().some((one) => one.includes("裁切范围"))).toBe(true);
    expect(rows().some((one) => one.includes("Crop amount"))).toBe(false);
    //: 组标题(节点名)也是表里挑出来的
    expect(document.querySelector('[data-source-group="720"] h5')!.textContent).toContain("修补裁切");

    setLocale("en-US");
    expect(rows().some((one) => one.includes("Crop amount"))).toBe(true);
    expect(rows().some((one) => one.includes("裁切范围"))).toBe(false);
    expect(document.querySelector('[data-source-group="720"] h5')!.textContent).toContain("Inpaint Crop");
  });

  it("插件只给一句的项(「跑几遍」)两种语言下都是那一句", () => {
    const { setLocale } = showAgain();
    const runs = () => document.querySelector('[data-source-item="runs"]')!.textContent ?? "";

    expect(runs()).toContain("跑几遍");
    setLocale("en-US");
    expect(runs()).toContain("跑几遍");
  });
});
