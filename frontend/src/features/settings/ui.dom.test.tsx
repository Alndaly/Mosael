/** @vitest-environment jsdom */
import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  SettingsBlock,
  SettingsBlockTitle,
  SettingsGroup,
  SettingsItemNote,
  SettingsItemRow,
  SettingsItemState,
  SettingsList,
  SettingsListBlock,
  SettingsListItem,
  SettingsRow,
  SettingsSectionStack,
  SettingsTag,
} from "@/components/settings/settings-layout";
import { CONTROL_HEIGHT } from "@/components/ui/control-size";

describe("settings section layout", () => {
  it("keeps groups flat inside the page panel", () => {
    const { container } = render(
      <SettingsGroup title="外观">
        <SettingsRow label="主题">深色</SettingsRow>
      </SettingsGroup>,
    );

    const content = container.querySelector('[data-slot="settings-group-content"]');
    const header = container.querySelector('[data-slot="settings-group-header"]');
    expect(content).not.toBeNull();
    expect(header).not.toHaveClass("border-b");
    expect(header).toHaveClass("pb-2");
    expect(content).not.toHaveClass("rounded-lg");
    expect(content).not.toHaveClass("border");
    expect(content).not.toHaveClass("bg-panel");
  });

  it("separates sections and gives the next header more breathing room", () => {
    const { container } = render(
      <SettingsSectionStack>
        <SettingsGroup title="外观" />
        <>
          <SettingsGroup title="背景" />
          <SettingsGroup title="自定义 CSS" />
        </>
      </SettingsSectionStack>,
    );

    expect(screen.getAllByRole("heading")).toHaveLength(3);
    // 线画在**后一节**身上,由相邻兄弟触发 —— 不再插一个独立的 Separator 元素。
    const stack = container.querySelector('[data-slot="settings-section-stack"]')!;
    expect(stack.querySelectorAll('[data-slot="separator"]')).toHaveLength(0);
    expect(stack.className).toContain("[&>[data-slot=settings-group]+[data-slot=settings-group]]:border-t");
    // 紧贴上一节,下面留出下一节标题的层级;不用 my-*,那会和上一节最后一行的内边距叠起来。
    expect(stack.className).toContain("[&>[data-slot=settings-group]+[data-slot=settings-group]]:mt-3");
    expect(stack.className).toContain("[&>[data-slot=settings-group]+[data-slot=settings-group]]:pt-7");
  });

  it("走 portal 的孩子不算一节 —— 末尾不会多出一条底下什么都没有的线", () => {
    /*
     * 数据与诊断那一页把 AlertDialog 放在了 stack 里(它行内什么都不渲染),而此前的实现是
     * 「index > 0 就先插一条 Separator」—— 于是页面末尾多出一条横线,底下什么都没有。
     * 同类的还有 `{cond && <Group/>}` 里那个 false。
     */
    const { container } = render(
      <SettingsSectionStack>
        <SettingsGroup title="数据与诊断" />
        {false && <SettingsGroup title="不会出现" />}
        {/* 一个只走 portal 的孩子 */}
        <>{null}</>
      </SettingsSectionStack>,
    );
    const stack = container.querySelector('[data-slot="settings-section-stack"]')!;
    expect(stack.querySelectorAll('[data-slot="settings-group"]')).toHaveLength(1);
    expect(stack.querySelectorAll('[data-slot="separator"]')).toHaveLength(0);
  });

  it("keeps rows and flat-list items on the same 20px vertical rhythm", () => {
    const { container } = render(
      <SettingsGroup title="模型">
        <SettingsRow label="默认模型">K3</SettingsRow>
        <SettingsList>
          <SettingsListItem>供应商 A</SettingsListItem>
        </SettingsList>
      </SettingsGroup>,
    );

    expect(container.querySelector('[data-slot="settings-row"]')).toHaveClass("py-5");
    expect(container.querySelector('[data-slot="settings-list-item"]')).toHaveClass("py-5");
  });

  it("gives the page, section, and row copy distinct typography levels", () => {
    const { container } = render(
      <SettingsSectionStack>
        <SettingsGroup title="外观" description="界面主题与语言">
          <SettingsRow label="主题" description="跟随系统自动切换">
            深色
          </SettingsRow>
        </SettingsGroup>
        <SettingsGroup title="背景与磨玻璃" />
      </SettingsSectionStack>,
    );

    const stack = container.querySelector('[data-slot="settings-section-stack"]');
    const titles = container.querySelectorAll('[data-slot="settings-group-title"]');
    const rowLabel = container.querySelector('[data-slot="settings-row-label"]');
    const rowDescription = container.querySelector('[data-slot="settings-row-description"]');

    expect(stack?.className).toContain("first-child_[data-slot=settings-group-title]");
    expect(titles[0]).toHaveClass("text-xl");
    expect(titles[1]).toHaveClass("text-xl");
    expect(rowLabel).toHaveClass("text-ui-md", "font-medium");
    expect(rowDescription).toHaveClass("text-ui-sm", "leading-[1.5]");
  });

  it("renders settings collections as divided flat rows", () => {
    const { container } = render(
      <SettingsList>
        <SettingsListItem>供应商 A</SettingsListItem>
        <SettingsListItem>供应商 B</SettingsListItem>
      </SettingsList>,
    );

    const list = container.firstElementChild;
    expect(list).toHaveClass("divide-y");
    expect(list?.firstElementChild).not.toHaveClass("border");
    expect(list?.firstElementChild).not.toHaveClass("rounded-md");
  });

  it("gives pure list sections a single vertical spacing owner", () => {
    const { container } = render(
      <SettingsListBlock>
        <SettingsListItem>飞书机器人</SettingsListItem>
      </SettingsListBlock>,
    );

    const block = container.querySelector('[data-slot="settings-list-block"]');
    expect(block).toBeInTheDocument();
    expect(block?.className).not.toMatch(/\bpy-/);
    expect(block?.querySelector('[data-slot="settings-list-item"]')).toHaveClass("py-5");
    //: 列表不许被压得比自己的行还矮:一页只有一节时,那一节被钉成整列高(SettingsSectionStack 的 only-child 规则),
    //: 列表带着 min-h-0 就被压扁,行画到下面的「邀请成员」上(团队页四五个成员时实测)。长了就让整列滚动。
    expect(block?.className).not.toMatch(/\bmin-h-0\b/);
  });

  it("keeps optional list tools inside the same spacing contract", () => {
    const { container } = render(
      <SettingsListBlock toolbar={<div>已选择 2 项</div>}>
        <SettingsListItem>成本规则</SettingsListItem>
      </SettingsListBlock>,
    );

    expect(container.querySelector('[data-slot="settings-list-toolbar"]')).toHaveClass("px-0.5", "pt-3");
    expect(container.querySelector('[data-slot="settings-list-block"]')?.className).not.toMatch(/\bpy-/);
  });

  it("can bound a long settings list and scroll it internally", () => {
    const { container } = render(
      <SettingsList scrollable>
        <SettingsListItem>团队动态</SettingsListItem>
      </SettingsList>,
    );

    expect(container.firstElementChild).toHaveClass("max-h-80", "overflow-y-auto", "overscroll-contain");
  });

  it("lets a single-section empty state fill the settings pane", () => {
    const { container } = render(
      <SettingsSectionStack>
        <SettingsGroup title="飞书机器人" contentClassName="min-h-0">
          <div>empty</div>
        </SettingsGroup>
      </SettingsSectionStack>,
    );

    expect(container.querySelector('[data-slot="settings-section-stack"]')).toHaveClass("h-full");
    expect(container.querySelector('[data-slot="settings-group"]')).toHaveClass("grid");
    expect(container.querySelector('[data-slot="settings-group-content"]')).toHaveClass("min-h-0");
  });

  it("lets the block own the distance between its title and content", () => {
    const { container } = render(
      <SettingsBlock>
        <SettingsBlockTitle>团队动态</SettingsBlockTitle>
        <SettingsList>
          <SettingsListItem>创建了画板</SettingsListItem>
        </SettingsList>
      </SettingsBlock>,
    );

    expect(container.querySelector('[data-slot="settings-block"]')).toHaveClass("gap-4", "py-5");
    const title = container.querySelector('[data-slot="settings-block-title"]');
    expect(title).toHaveClass("m-0");
    expect(title?.className).not.toMatch(/m[tyb]-/);
  });

  it("an item row sits in the group like any other row: same rhythm, divider from the group, no card frame", () => {
    const { container } = render(
      <SettingsGroup title="转写模型">
        <SettingsRow label="默认模型">K3</SettingsRow>
        <SettingsItemRow label="FunASR" meta={["funasr", null, "973 MB"]} description="中文好">
          <button type="button">下载</button>
        </SettingsItemRow>
      </SettingsGroup>,
    );

    const row = container.querySelector('[data-slot="settings-item-row"]')!;
    expect(row.parentElement).toHaveAttribute("data-slot", "settings-group-content");
    expect(row).toHaveClass("py-5", "px-0.5");
    expect(row).not.toHaveClass("border");
    expect(row).not.toHaveClass("rounded-lg");
    expect(row).not.toHaveClass("bg-background");
    // 标签和说明与 SettingsRow 同一档字号。
    expect(container.querySelector('[data-slot="settings-item-label"]')).toHaveClass("text-ui-md", "font-medium");
    expect(container.querySelector('[data-slot="settings-item-description"]')).toHaveClass("text-ui-sm", "leading-[1.5]");
    // 元信息是一行小字,假值跳过,「·」隔开。
    const meta = container.querySelector('[data-slot="settings-item-meta"]')!;
    expect(meta).toHaveTextContent("funasr · 973 MB");
    expect(meta).toHaveClass("text-muted-foreground");
    expect(screen.getByRole("button", { name: "下载" }).parentElement).toHaveAttribute("data-slot", "settings-item-control");
  });

  it("puts status lines under the description and progress across the whole row", () => {
    const { container } = render(
      <SettingsItemRow
        label="Demucs"
        notes={<SettingsItemNote tone="destructive">pip 失败</SettingsItemNote>}
        footer={<div>进度</div>}
      />,
    );

    const note = screen.getByText("pip 失败");
    expect(note).toHaveAttribute("data-slot", "settings-item-note");
    expect(note).toHaveClass("text-destructive", "text-ui-sm");
    const footer = container.querySelector('[data-slot="settings-item-footer"]')!;
    expect(footer).toHaveTextContent("进度");
    expect(footer.className).toContain("col-span-2");
    // 没有右边的控件就不留那一格。
    expect(container.querySelector('[data-slot="settings-item-control"]')).toBeNull();
    expect(container.querySelector('[data-slot="settings-item-meta"]')).toBeNull();
  });

  it("keeps a status in the control slot as tall as the sm button it replaces", () => {
    render(
      <SettingsItemRow label="F5-TTS">
        <SettingsItemState tone="success">已安装</SettingsItemState>
      </SettingsItemRow>,
    );

    const state = screen.getByText("已安装");
    expect(state).toHaveClass(CONTROL_HEIGHT.sm, "text-success");
  });

  it("draws tags quietly: tinted, no outline, no uppercase", () => {
    render(<SettingsTag tone="warning">会去掉音乐</SettingsTag>);
    const tag = screen.getByText("会去掉音乐");
    expect(tag).toHaveClass("rounded-full", "text-warning");
    expect(tag).not.toHaveClass("border");
    expect(tag).not.toHaveClass("uppercase");
  });
});

/**
 * 维护者:「有不少页面依然 title 下面的描述右侧有很大的间距」。
 *
 * 说明写死 `max-w-2xl`(42rem),而设置页是整页宽、下面紧跟满宽的行 —— 说明早早折在 42rem,
 * 右边空出一大块。管理页的同类段落(AdminSection)已经在 0bb1a33f3 改掉;设置页这份是设置各页
 * 共用的节头(`SettingsGroup`,管理页的 AdminSection 是同一版式),同一种「节说明」只能有一种规则:
 * 宽度交给这一列,不再在说明身上设上限。
 *
 * 窄容器(弹窗、侧栏)里的正文**不在这条规则里** —— 那些地方的行长本来就短,限宽是对的,
 * 所以下面第二条钉的是「窄容器里说明铺满、不横滚」,而不是「窄容器里也把上限拿掉」。
 */
describe("SettingsGroup 的说明", () => {
  it("说明不再限宽:类里没有 max-w-*,跟着这一列铺开", () => {
    render(<SettingsGroup title="自动放行准则" description="这几类操作按什么判" />);

    const description = screen.getByText("这几类操作按什么判");
    expect(description.tagName).toBe("P");
    expect(description).toHaveAttribute("data-slot", "settings-group-description");
    //: 没有宽度上限(此前的 max-w-2xl 就是那处大间距)。
    expect(description.className.split(/\s+/).filter((token) => token.startsWith("max-w-"))).toEqual([]);
    //: 字号/颜色仍是同一套,只是不再截宽。
    expect(description).toHaveClass("text-ui-md", "text-muted-foreground");
  });

  it("窄容器里说明能铺满:没有宽度上限、也没被塞进横向滚动的框里", () => {
    const long = "这是一段很长的说明,".repeat(20);
    const { container } = render(
      <div style={{ width: 320 }}>
        <SettingsGroup title="窄" description={long} />
      </div>,
    );

    const description = container.querySelector<HTMLElement>('[data-slot="settings-group-description"]')!;
    expect(description).not.toBeNull();
    const tokens = description.className.split(/\s+/);
    //: 宽度跟着容器走:不写 max-w-*、不写 w-max、也不禁换行。
    expect(tokens.filter((token) => token.startsWith("max-w-") || token === "w-max" || token === "whitespace-nowrap")).toEqual([]);
    //: 块级 p 在 min-w-0 的格子里:宽度 auto = 这一列的宽,不是内容宽。
    expect(description.tagName).toBe("P");
    expect(description.parentElement).toHaveClass("min-w-0");
    expect(description.parentElement).not.toHaveClass("w-fit", "w-max", "inline-block");
    //: 说明不在一个会横向滚动的容器里。
    expect(description.closest(".overflow-x-auto, .overflow-x-scroll")).toBeNull();
  });
});
