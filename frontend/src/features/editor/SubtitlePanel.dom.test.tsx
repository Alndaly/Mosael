/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { describe, expect, it, vi } from "vitest";

import { readHint } from "@/test/hint";

/**
 * 字幕面板:列表本身,以及去「配音」页的入口。
 *
 * 配音不在这里做(表单在配音页,见 VoicePanel.dom.test)。这里钉住的是**入口还在**:
 * 每条字幕旁边一个 —— 「就这一条重配一下」时你正看着它、手就在它上面 —— 点了要选中那一条
 * 再切过去,配音页的范围跟着选中走。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

// radix 的滑杆量自己的尺寸,jsdom 没有 ResizeObserver。
vi.stubGlobal("ResizeObserver", class {
  observe() {}
  unobserve() {}
  disconnect() {}
});

import { SubtitlePanel } from "@/features/editor/SubtitlePanel";
import { useEditorStore } from "@/features/editor/editorStore";

function sequenceWith(texts: string[]) {
  return {
    id: "s1",
    workspace_id: "w1",
    revision: 1,
    tracks: [
      {
        id: "t1",
        kind: "subtitle",
        clips: texts.map((text, index) => ({
          id: `c${index}`,
          asset_id: null,
          asset_kind: "",
          timeline_start: index * 5,
          src_in: 0,
          src_out: 3,
          speed: 1,
          text_override: text,
        })),
      },
    ],
  } as never;
}

function renderPanel(texts: string[], onDub?: () => void) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SubtitlePanel
        sequence={sequenceWith(texts)}
        onSetText={vi.fn()}
        onAddSubtitle={vi.fn()}
        onDeleteClip={vi.fn()}
        onDub={onDub}
      />
    </QueryClientProvider>,
  );
}

describe("字幕列表空状态", () => {
  it("没有字幕时整块居中,而不是钉在顶上留一屏空白", () => {
    const { container } = renderPanel([]);
    const list = container.querySelector(".overflow-y-auto");
    // jsdom 没有真实布局,量不了像素;钉住的是**决定布局的那个类**,回归时它会先没。
    expect(list?.className).toContain("content-center");
    expect(list?.className).not.toContain("content-start");
  });

  it("有字幕时贴顶排列 —— 居中只属于空状态", () => {
    const { container } = renderPanel(["一条"]);
    const list = container.querySelector(".overflow-y-auto");
    expect(list?.className).toContain("content-start");
    expect(list?.className).not.toContain("content-center");
  });
});

describe("去配音页的入口", () => {
  it("每条字幕自己带一个入口", () => {
    renderPanel(["第一条", "第二条"], vi.fn());
    expect(screen.getAllByLabelText("subtitleDubThis")).toHaveLength(2);
  });

  it("点某一条的入口:只配那一条切到配音页,不动时间线上的选中", async () => {
    const onDub = vi.fn();
    useEditorStore.getState().selectClip("c0");
    renderPanel(["第一条", "第二条"], onDub);
    await userEvent.click(screen.getAllByLabelText("subtitleDubThis")[1]);
    expect(onDub).toHaveBeenCalledWith("c1");
    expect(useEditorStore.getState().selectedClipIds).toEqual(["c0"]);
  });

  it("顶部动作区的「配音」也切过去,不再在这里弹一张表单", async () => {
    const onDub = vi.fn();
    renderPanel(["一条"], onDub);
    await userEvent.click(screen.getByRole("button", { name: "subtitleDub" }));
    expect(onDub).toHaveBeenCalledOnce();
    expect(screen.queryByText("subtitleDubLine")).toBeNull();
  });
});

/** 动作区要齐 7 个动作,还要有「字幕样式」:别的用例只管列表,这一份把面板装满。 */
function renderAll() {
  const onSetStyle = vi.fn();
  const onPreviewStyle = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <SubtitlePanel
        sequence={sequenceWith(["第一条"])}
        onSetText={vi.fn()}
        onAddSubtitle={vi.fn()}
        onGenerate={vi.fn()}
        onDeleteClip={vi.fn()}
        onDub={vi.fn()}
        onApplyTexts={vi.fn(async () => ({}))}
        onImportFile={vi.fn()}
        style={{}}
        onSetStyle={onSetStyle}
        onPreviewStyle={onPreviewStyle}
      />
    </QueryClientProvider>,
  );
  return { ...view, onSetStyle, onPreviewStyle };
}

/** 面板上的 7 个动作,按它们自己的名字找。 */
function actionButtons() {
  return [
    screen.getByRole("button", { name: "subtitleGenerate" }),
    screen.getByRole("button", { name: "addSubtitleAtPlayhead" }),
    screen.getByRole("button", { name: "subtitleTranslate" }),
    screen.getByRole("button", { name: "subtitleDub" }),
    screen.getByRole("button", { name: "subtitleFileImport" }),
    screen.getByRole("button", { name: "subtitleFileExport" }),
    screen.getByRole("button", { name: /全部存为笔记/ }),
  ];
}

describe("顶部动作区", () => {
  it("7 个动作都在列表之前,底部不再有一排", () => {
    const { container } = renderAll();
    const root = container.firstElementChild as HTMLElement;
    const list = root.querySelector(".overflow-y-auto") as HTMLElement;
    expect(list).not.toBeNull();
    for (const button of actionButtons()) {
      expect(list.contains(button)).toBe(false);
      // list 在按钮之后 ⇒ 按钮在列表之前。
      expect(button.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
    // 列表就是面板的最后一个子元素:原来那排钉子已经删掉,不是两处都有。
    expect(root.lastElementChild).toBe(list);
  });

  it("四组按语义分开:生成 | 加工 | 文件 | 设置,每组之间一条发丝线", () => {
    const { container } = renderAll();
    const bar = container.querySelector("[data-subtitle-actions]") as HTMLElement;
    expect(bar).not.toBeNull();
    const groups = [...bar.querySelectorAll<HTMLElement>("[data-actions-group]")];
    expect(groups.map((group) => group.dataset.actionsGroup)).toEqual(["generate", "process", "files", "style"]);
    const names = (group: HTMLElement) =>
      [...group.querySelectorAll("button")].map((button) => button.getAttribute("aria-label"));
    expect(groups.map(names)).toEqual([
      ["subtitleGenerate", "addSubtitleAtPlayhead"],
      ["subtitleTranslate", "subtitleDub"],
      ["subtitleFileImport", "subtitleFileExport", "全部存为笔记"],
      ["subtitleStyle"],
    ]);
    // 三条发丝线,不是 8 颗同款按钮一路排下去。
    const dividers = [...bar.querySelectorAll("[data-actions-divider]")];
    expect(dividers).toHaveLength(3);
    for (const divider of dividers) {
      expect(divider).toHaveAttribute("aria-hidden", "true");
    }
  });

  it("窄宽度下折行,不横向滚动,按钮自己不被压窄", () => {
    const { container } = renderAll();
    const bar = container.querySelector("[data-subtitle-actions]") as HTMLElement;
    // jsdom 没有布局:钉住决定这件事的类,回归时它会先没。
    expect(bar.className).toContain("flex-wrap");
    expect(bar.className).not.toMatch(/overflow-x-(auto|scroll)/);
    const root = container.firstElementChild as HTMLElement;
    expect(root.className).not.toMatch(/overflow-x-(auto|scroll)/);
    for (const button of actionButtons()) {
      // 按钮整颗换行,而不是把自己压窄、把字挤断。
      expect(button.className).toContain("shrink-0");
      expect(button.className).toContain("whitespace-nowrap");
    }
    expect(bar.contains(screen.getByRole("button", { name: "subtitleStyle" }))).toBe(true);
  });

  it("折行时分隔线跟着自己的组走,不会孤零零落在行尾", () => {
    const { container } = renderAll();
    const bar = container.querySelector("[data-subtitle-actions]") as HTMLElement;
    const units = [...bar.querySelectorAll<HTMLElement>("[data-actions-unit]")];
    expect(units).toHaveLength(4);
    // 一个单元 = 一条线 + 它后面那一组。单元自己不折行,所以线永远挨着组;
    // 折行只发生在单元与单元之间(flex-wrap 在栏上)。
    expect(units.map((unit) => unit.querySelectorAll("[data-actions-divider]").length)).toEqual([0, 1, 1, 1]);
    for (const unit of units) {
      expect(unit.className).toContain("inline-flex");
      expect(unit.className).toContain("shrink-0");
      expect(unit.className).not.toContain("flex-wrap");
      expect(unit.querySelectorAll("[data-actions-group]")).toHaveLength(1);
    }
    // 线在单元里,不是栏的直接子元素 —— 直接挂在 flex-wrap 的栏上才会被单独甩到下一行。
    for (const divider of bar.querySelectorAll("[data-actions-divider]")) {
      expect(divider.parentElement).not.toBe(bar);
      expect(divider.parentElement?.hasAttribute("data-actions-unit")).toBe(true);
    }
    // 组内 4px;组间是两侧各 6px 加一条 1px 线(13px),近的是同类、远的是异类。
    for (const group of bar.querySelectorAll<HTMLElement>("[data-actions-group]")) {
      expect(group.className).toContain("gap-1");
    }
    expect(bar.className).toContain("gap-x-1.5");
    for (const unit of units) expect(unit.className).toContain("gap-1.5");
  });
});

/**
 * 维护者:「逐字稿和字幕的这些交互入口按钮可以改为 icon 模式的 button 然后注意 Hint」。
 *
 * 顶上 7 个动作 + 「字幕样式」都只画图标:读屏名字在 aria-label,悬停说明在 Hint(不是 title),
 * 计数之类的补充说明跟着进 Hint。动作本身一个都没少、行为不变 —— 行为由其它用例钉。
 */
describe("顶部动作区是图标按钮", () => {
  /** 7 个动作 + 「字幕样式」,按自己的名字找(字幕样式也统一成图标款)。 */
  function iconActions() {
    return [
      screen.getByRole("button", { name: "subtitleGenerate" }),
      screen.getByRole("button", { name: "addSubtitleAtPlayhead" }),
      screen.getByRole("button", { name: "subtitleTranslate" }),
      screen.getByRole("button", { name: "subtitleDub" }),
      screen.getByRole("button", { name: "subtitleFileImport" }),
      screen.getByRole("button", { name: "subtitleFileExport" }),
      screen.getByRole("button", { name: "全部存为笔记" }),
      screen.getByRole("button", { name: "subtitleStyle" }),
    ];
  }

  it("只有图标:没有可见文字、名字在 aria-label、标准 32px 方钮、不压扁", () => {
    renderAll();
    for (const button of iconActions()) {
      expect(button.getAttribute("aria-label"), "icon-only 的按钮必须给读屏一个名字").toBeTruthy();
      expect(button.textContent).toBe("");
      expect(button.className).toContain("size-8");
      expect(button.className).toContain("shrink-0");
      expect(button.hasAttribute("title")).toBe(false);
      expect(button.hasAttribute("data-hint-trigger")).toBe(true);
    }
  });

  it("每个图标按钮都有 Hint:动作名 + 一句说明", async () => {
    renderAll();
    const expected: Array<[string, string]> = [
      ["subtitleGenerate", "subtitleGenerateHint"],
      ["addSubtitleAtPlayhead", "addSubtitleAtPlayheadHint"],
      ["subtitleTranslate", "subtitleTranslateHint"],
      ["subtitleDub", "subtitleDubHint"],
      ["subtitleFileImport", "subtitleFileImportHint"],
      ["subtitleFileExport", "subtitleFileExportHint"],
      ["全部存为笔记", "把整条字幕轨存成一篇笔记"],
      ["subtitleStyle", "subtitleStyleHint"],
    ];
    for (const [name, explanation] of expected) {
      const hint = await readHint(screen.getByRole("button", { name }));
      expect(hint, name).toContain(name);
      expect(hint, name).toContain(explanation);
    }
  });
});

describe("「字幕样式」和同排动作是同一款", () => {
  const classesOf = (element: Element) => new Set(element.className.split(/\s+/).filter(Boolean));

  it("用同一款图标钮,不再单独做成文字药丸", () => {
    renderAll();
    const style = screen.getByRole("button", { name: "subtitleStyle" });
    // 同排每个动作的每一个外观 token,「字幕样式」都得有 —— 这是「同一款」最直接的写法。
    for (const name of ["subtitleGenerate", "addSubtitleAtPlayhead", "subtitleDub", "全部存为笔记"]) {
      const sibling = screen.getByRole("button", { name });
      for (const token of classesOf(sibling)) expect(classesOf(style).has(token), `${name}: ${token}`).toBe(true);
    }
    // 同排是图标动作:它也得只有图标,不再是 PILL 那一款文字按钮。
    expect(style.textContent).toBe("");
    expect(style.className).not.toContain("text-ui-xs");
    expect(style.className).not.toContain("px-[9px]");
    expect(style.className).not.toContain("border-field-border");
  });

  it("高度 / 图标尺寸和同排动作一致 —— 差一档就又是另一款", () => {
    renderAll();
    const style = screen.getByRole("button", { name: "subtitleStyle" });
    const action = screen.getByRole("button", { name: "addSubtitleAtPlayhead" });
    // jsdom 没有排版:钉住决定高度、图标尺寸的类。同一排都是 32px 方钮、16px 图标。
    for (const token of ["size-8", "rounded-md", "[&_svg]:size-4", "shrink-0"]) {
      expect(style.className, token).toContain(token);
      expect(action.className, token).toContain(token);
    }
  });

  it("紧跟在「全部存为笔记」后面,不再用 ml-auto 单独甩到最右", () => {
    renderAll();
    const style = screen.getByRole("button", { name: "subtitleStyle" });
    const saveAll = screen.getByRole("button", { name: /全部存为笔记/ });
    expect(
      saveAll.compareDocumentPosition(style) & Node.DOCUMENT_POSITION_FOLLOWING,
      "它该排在其它动作之后",
    ).toBeTruthy();
    // 同一排的下一颗动作靠工具栏自己的 gap 排过去,而不是把自己推到另一头当成另一类。
    expect(style.className).not.toContain("ml-auto");
  });

  it("点它仍然打开同一个字幕样式弹窗(回归)", async () => {
    const user = userEvent.setup();
    renderAll();
    const style = screen.getByRole("button", { name: "subtitleStyle" });
    expect(style).toHaveAttribute("aria-haspopup", "dialog");
    await user.click(style);
    const dialogs = screen.getAllByRole("dialog");
    expect(dialogs).toHaveLength(1);
    expect(within(dialogs[0]!).getByText("subtitleStyle")).toBeTruthy();
    expect(within(dialogs[0]!).getByLabelText("subColor")).toBeTruthy();
  });
});

describe("字幕样式弹窗", () => {
  it("默认看不到样式设置,也没有折叠区那套展开状态", () => {
    renderAll();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByLabelText("subColor")).toBeNull();
    // 它现在是**弹窗**的触发器,不再是那一排折叠区(折叠区只有一个 aria-expanded)。
    const trigger = screen.getByRole("button", { name: "subtitleStyle" });
    expect(trigger).toHaveAttribute("aria-haspopup", "dialog");
  });

  it("点「字幕样式」→ 弹窗出现,原来那些设置项都在里面", async () => {
    const user = userEvent.setup();
    renderAll();
    await user.click(screen.getByRole("button", { name: "subtitleStyle" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("subtitleStyle")).toBeTruthy();
    // 原样搬过来的七样设置 + 加粗那一切换键。
    for (const label of ["subFont", "subFontSize", "subColor", "subBg", "subBgOpacity", "subPosition", "subOffset"]) {
      expect(within(dialog).getByLabelText(label), label).toBeTruthy();
    }
    expect(within(dialog).getByRole("button", { name: "subBold" })).toBeTruthy();
    expect(within(dialog).getAllByRole("group")).toHaveLength(3);
  });

  it("关掉就没了", async () => {
    const user = userEvent.setup();
    renderAll();
    await user.click(screen.getByRole("button", { name: "subtitleStyle" }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByLabelText("subColor")).toBeNull();
  });

  it("在弹窗里改一项立刻生效(不是等「完成」才写)", async () => {
    const user = userEvent.setup();
    const { onSetStyle } = renderAll();
    await user.click(screen.getByRole("button", { name: "subtitleStyle" }));
    const dialog = screen.getByRole("dialog");
    // 默认加粗是开着的(见 subtitleStyle 的 SUBTITLE_DEFAULTS),点一下就地关掉 —— 写回马上发生。
    await user.click(within(dialog).getByRole("button", { name: "subBold" }));
    expect(onSetStyle).toHaveBeenLastCalledWith(expect.objectContaining({ bold: false }));
  });
});

describe("字幕样式设置(弹窗里)", () => {
  function renderStyle(style: Record<string, unknown> = {}) {
    const onSetStyle = vi.fn();
    const onPreviewStyle = vi.fn();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const view = render(
      <QueryClientProvider client={client}>
        <SubtitlePanel
          sequence={sequenceWith(["一条"])}
          onSetText={vi.fn()}
          onAddSubtitle={vi.fn()}
          onDeleteClip={vi.fn()}
          style={style}
          onSetStyle={onSetStyle}
          onPreviewStyle={onPreviewStyle}
          onUploadFont={vi.fn()}
        />
      </QueryClientProvider>,
    );
    return { ...view, onSetStyle, onPreviewStyle };
  }

  it("三组各有名字,组名不和组里任何一行重名(此前是「位置 / 位置」)", async () => {
    renderStyle();
    await userEvent.click(screen.getByRole("button", { name: /subtitleStyle/ }));
    // 设置搬进了弹窗(portal 到 body),所以按 document 找,不按 render 的容器找。
    const groups = screen.getAllByRole("group");
    expect(groups.map((group) => group.getAttribute("aria-labelledby") && document.getElementById(group.getAttribute("aria-labelledby")!)?.textContent))
      .toEqual(["subGroupText", "subGroupBackplate", "subGroupPlacement"]);
    for (const group of groups) {
      const name = document.getElementById(group.getAttribute("aria-labelledby")!)?.textContent;
      const rowLabels = [...group.querySelectorAll("[data-style-row] > span:first-child")].map((span) => span.textContent);
      expect(rowLabels).not.toContain(name);
    }
    // 组名本身的文案也不能撞上行名 —— 同一套键在中文里曾经都叫「位置」。
    const messages = (await import("@/app/messages")).messages;
    for (const locale of Object.values(messages) as Record<string, string>[]) {
      expect(locale.subGroupPlacement).not.toBe(locale.subPosition);
      expect(locale.subGroupBackplate).not.toBe(locale.subBg);
    }
  });

  it("每一行是同一副三列骨架:标签列、控件列、读数列定宽,控件的左右缘对齐", async () => {
    renderStyle();
    await userEvent.click(screen.getByRole("button", { name: /subtitleStyle/ }));
    const rows = [...document.querySelectorAll("[data-style-row]")];
    expect(rows).toHaveLength(8);
    for (const row of rows) expect(row.className).toContain("grid-cols-[56px_minmax(0,1fr)_36px]");
    // 滑杆的读数落在第三列,等宽数字。
    const readouts = [...document.querySelectorAll("[data-style-row] output")];
    expect(readouts.map((one) => one.textContent)).toEqual(["32", "50%", "8%"]);
    for (const one of readouts) expect(one.className).toContain("timecode");
  });

  it("颜色是紧凑色块 + 十六进制读数,不再是铺满整行的长条", async () => {
    renderStyle({ color: "#ffcc00" });
    await userEvent.click(screen.getByRole("button", { name: /subtitleStyle/ }));
    const swatch = screen.getByLabelText("subColor");
    expect(swatch).toHaveAttribute("type", "color");
    expect(swatch.className).toContain("w-9");
    expect(swatch.className).not.toContain("flex-1");
    expect(swatch.parentElement).toHaveTextContent("#ffcc00");
    expect(screen.getByLabelText("subBg").className).toContain("w-9");
  });

  it("在取色盘里拖动只预览,选定(原生 change)才写回 —— 此前拖一下写几十次库、记几十步撤销", async () => {
    const { onSetStyle, onPreviewStyle } = renderStyle();
    await userEvent.click(screen.getByRole("button", { name: /subtitleStyle/ }));
    const swatch = screen.getByLabelText("subColor") as HTMLInputElement;
    for (const color of ["#110000", "#220000", "#330000"]) fireEvent.input(swatch, { target: { value: color } });
    expect(onPreviewStyle).toHaveBeenLastCalledWith(expect.objectContaining({ color: "#330000" }));
    expect(onSetStyle).not.toHaveBeenCalled();
    swatch.dispatchEvent(new Event("change", { bubbles: true }));
    expect(onSetStyle).toHaveBeenCalledOnce();
    expect(onSetStyle).toHaveBeenLastCalledWith(expect.objectContaining({ color: "#330000" }));
  });

  it("加粗自成一行,是一个按下 / 抬起的切换键,写回的字段不变", async () => {
    const { onSetStyle } = renderStyle({ bold: true });
    await userEvent.click(screen.getByRole("button", { name: /subtitleStyle/ }));
    const bold = screen.getByRole("button", { name: "subBold" });
    expect(bold).toHaveAttribute("aria-pressed", "true");
    // 和颜色不在同一行。
    expect(bold.closest("[data-style-row]")).not.toBe(screen.getByLabelText("subColor").closest("[data-style-row]"));
    await userEvent.click(bold);
    expect(onSetStyle).toHaveBeenLastCalledWith(expect.objectContaining({ bold: false, color: "#ffffff", position: "bottom" }));
  });
});
